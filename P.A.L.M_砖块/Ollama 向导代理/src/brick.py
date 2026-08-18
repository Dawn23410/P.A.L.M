"""Ollama 向导代理砖块。

把本机 Ollama 的 HTTP API 暴露给前端「引导」向导：
- GET  /api/ollama/health      运行检测（Ollama 是否在 base_url 监听）
- GET  /api/ollama/guide       向导规格：安装/运行检测 + 预置模型清单 + 默认参数
- GET  /api/ollama/catalog     模型目录（国内 HF 镜像 + 魔搭社区双来源，含名称/版本/参数量/体积）
- POST /api/ollama/download    后台下载模型（分片 + 断点续传），返回 job_id
- GET  /api/ollama/download/{id}     轮询下载进度（总量/已下/速度/ETA）
- GET  /api/ollama/download/active/{key}  取该模型进行中的下载任务（重入向导续接）
- POST /api/ollama/upload      保存拖拽上传的本地 GGUF（校验魔数）
- POST /api/ollama/deploy      部署模型（ollama create：Modelfile FROM 本地 GGUF + 高级参数）
- POST /api/ollama/pull        拉取模型（代理 /api/pull，非流式等待完成）
- POST /api/ollama/pull-stream 流式拉取模型（SSE 实时进度）
- POST /api/ollama/import-gguf 导入本地 GGUF（校验魔数 → 上传 blob → /api/create）

不再包含 SafeTensors 转换（llama.cpp 已移除）。
仅操作 localhost 的 Ollama，符合「模型发现」同源思路；缺失 httpx 时给出清晰报错。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from palm_sdk.net import arequest, is_card_present  # Ollama 本地 API 经网卡门面（回环放行）

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from palm_sdk.bricks.base import Brick, BrickManifest
from .connection import _hosts_for, _is_tcp_up, _ollama_running
from .catalog import build_catalog, resolve_model
from .downloader import DownloadError, manager
from .convert import is_ollama_capable, ollama_pull_stream

logger = get_logger(__name__)

DEFAULT_OLLAMA = "http://localhost:11434"




def _resolve_source(srcs: dict, source: str) -> tuple[Optional[str], Optional[dict]]:
    """解析下载来源。source="auto"（默认）时自动挑选首个可用来源（魔搭优先，回退 HF）。

    优先级：魔搭社区 > HF 镜像。无魔搭单文件时自动用 HF；两者都有则优先魔搭。
    """
    srcs = srcs or {}
    if source and source != "auto" and srcs.get(source, {}).get("url"):
        return source, srcs[source]
    for s in ("modelscope", "hf"):
        if srcs.get(s, {}).get("url"):
            return s, srcs[s]
    return None, None

# 向导预设模型清单（之前硬编码在前端，现统一由本砖块下发，前端仅收集选择）。
OLLAMA_PRESETS = [
    {"value": "llama3.2", "label": "Llama 3.2（轻量，推荐入门）"},
    {"value": "llama3.1", "label": "Llama 3.1"},
    {"value": "qwen2.5", "label": "Qwen 2.5"},
    {"value": "deepseek-r1", "label": "DeepSeek-R1（推理）"},
    {"value": "phi3", "label": "Phi 3"},
    {"value": "mistral", "label": "Mistral"},
    {"value": "gemma2", "label": "Gemma 2"},
]

# 向导默认模型参数（仅 UI 预留，暂不接入对话）。
DEFAULT_PARAMS = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2048}

router = APIRouter(prefix="/api/ollama", tags=["ollama"])


def _base(base_url: Optional[str]) -> str:
    """返回 Ollama 原生 API 基址（host 根，如 http://localhost:11434）。

    向导传入的 base_url 往往是 LLM 提供商的 OpenAI 兼容地址（带 /v1 后缀，例如
    http://localhost:11434/v1）。Ollama 的原生管理 API（/api/create、/api/pull、
    /api/tags 等）挂在 host 根、没有 /v1；若不剥掉会拼成 .../v1/api/create 这类
    Ollama 不存在的路由，返回 404。这里统一归一到 host 根。
    """
    u = (base_url or DEFAULT_OLLAMA).rstrip("/")
    while u.lower().endswith("/v1"):
        u = u[: -len("/v1")].rstrip("/")
    return u


def _require_httpx() -> None:
    if not is_card_present():
        raise HTTPException(500, "网卡未挂载，无法代理到 Ollama（需启用网卡砖）")


@router.get("/health", dependencies=[Depends(require_api_token)])
async def health(base_url: Optional[str] = None):
    """检测 Ollama 是否运行（多主机 socket 探测，规避 IPv4/IPv6 解析差异）。"""
    url = _base(base_url)
    running, version, error = await asyncio.to_thread(_ollama_running, url)
    return {"running": running, "base_url": url, "version": version, "error": error}


@router.get("/guide", dependencies=[Depends(require_api_token)])
async def guide(base_url: Optional[str] = None):
    """向导规格：检测 Ollama 是否已安装/运行，并下发模型清单与默认参数。

    前端「引导」向导打开时拉取此端点，据此决定是否需要「安装」步骤、
    渲染哪些模型可选、参数默认值是多少——前端本身不硬编码任何流程。
    """
    url = _base(base_url)
    running, version, error = await asyncio.to_thread(_ollama_running, url)
    # 已安装：服务在运行，或 ollama 可执行文件在 PATH 上（即便未启动服务）。
    on_path = shutil.which("ollama") is not None
    installed = running or on_path
    return {
        "base_url": url,
        "installed": installed,
        "running": running,
        "version": version,
        "skip_install": installed,  # 已安装则前端跳过「安装 Ollama」步骤
        "models": OLLAMA_PRESETS,
        "default_params": DEFAULT_PARAMS,
        "error": error,
    }


@router.post("/pull", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.pull_model"))])
async def pull(body: dict):
    """代理 Ollama 拉取模型（非流式，等待完成）。"""
    _require_httpx()
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(400, "model 不能为空")
    url = _base(body.get("base_url"))
    try:
        # 经网卡门面转发（localhost Ollama，回环放行）。
        r = await arequest("POST", url + "/api/pull", json={"name": model, "stream": False}, timeout=600.0)
        if r.status_code != 200:
            raise HTTPException(502, f"ollama pull 失败：{r.status_code} {r.text[:300]}")
        return {"status": "ok", "model": model}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"ollama pull 异常：{e}")


@router.post("/pull-stream", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.pull_model"))])
async def pull_stream(body: dict):
    """流式拉取模型（SSE 实时进度），直接调 ``ollama pull`` CLI。"""
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(400, "model 不能为空")

    async def event_gen():
        async for event in ollama_pull_stream(model):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/import-gguf", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.pull_model"))])
async def import_gguf(
    file: UploadFile = File(...),
    name: str = Form(...),
    base_url: Optional[str] = Form(None),
):
    """导入本地 GGUF：校验魔数 → 上传 blob → 创建模型。"""
    _require_httpx()
    gguf_content = await file.read()
    # 完整性校验：GGUF 魔数为前 4 字节 "GGUF"。
    if gguf_content[:4] != b"GGUF":
        raise HTTPException(400, "文件不是有效的 GGUF 模型（魔数校验失败）")
    model_name = (name or "").strip().replace(" ", "_")
    if not model_name:
        raise HTTPException(400, "模型名称不能为空")
    url = _base(base_url)
    digest = "sha256:" + hashlib.sha256(gguf_content).hexdigest()
    try:
        # 经网卡门面转发（localhost Ollama，回环放行）。
        # 1) 上传 blob（已存在返回 200，新上传返回 201）。
        r = await arequest(
            "POST", url + "/api/blobs/" + digest,
            content=gguf_content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=600.0,
        )
        if r.status_code not in (200, 201):
            raise HTTPException(502, f"blob 上传失败：{r.status_code} {r.text[:200]}")
        # 2) 创建模型（新版 API：files 映射，不再用 modelfile）。
        r2 = await arequest(
            "POST", url + "/api/create",
            json={"model": model_name, "files": {"model.gguf": digest}, "stream": False},
            timeout=600.0,
        )
        if r2.status_code != 200:
            raise HTTPException(502, f"模型创建失败：{r2.status_code} {r2.text[:300]}")
        return {"status": "ok", "model": model_name, "digest": digest}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"GGUF 导入异常：{e}")


def _safe_name(name: str) -> str:
    """把模型名清洗为安全文件名（去空格、非单词字符转下划线）。

    与 file/storage._safe_name 同名但职责不同：后者取上传文件的 basename 防路径穿越，
    本函数仅做模型名字符规整，不剥离路径。
    """
    return name.strip().replace(" ", "_").replace("/", "_").replace("\\", "_") or "model"



def _sha256_chunked(path: str) -> str:
    """分块读取文件计算 SHA256，避免大文件全读入内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return "sha256:" + h.hexdigest()


async def _file_async_iter(path: str, chunk_size: int = 8 * 1024 * 1024):
    """异步迭代文件块，用于流式上传，避免大文件全读入内存。"""
    loop = asyncio.get_running_loop()
    with open(path, "rb") as f:
        while True:
            chunk = await loop.run_in_executor(None, f.read, chunk_size)
            if not chunk:
                break
            yield chunk


@router.get("/catalog", dependencies=[Depends(require_api_token)])
async def catalog():
    """模型目录：按「模型名称→版本→参数量」分组的树，含各精度 HF/魔搭双来源 URL。

    前端据此渲染「模型名称 / 版本 / 参数量 / 量化精度」四个联动下拉，来源由后端自动优选。
    """
    return {"families": build_catalog(), "mirrors": ["hf", "modelscope"]}


OLLAMA_LIBRARY = [
    {"id": "llama3.2", "name": "Llama 3.2", "size": "3B / 1B", "desc": "Meta 轻量版，适合入门"},
    {"id": "llama3.1", "name": "Llama 3.1", "size": "8B / 70B / 405B", "desc": "Meta 主力开源模型"},
    {"id": "llama3.2-vision", "name": "Llama 3.2 Vision", "size": "11B / 90B", "desc": "Meta 多模态视觉模型"},
    {"id": "qwen2.5", "name": "Qwen 2.5", "size": "0.5B → 72B", "desc": "阿里通义千问系列"},
    {"id": "qwen2.5-coder", "name": "Qwen 2.5 Coder", "size": "1.5B / 7B / 32B", "desc": "阿里代码专用模型"},
    {"id": "deepseek-r1", "name": "DeepSeek-R1", "size": "1.5B / 7B / 8B / 14B / 32B / 70B / 671B", "desc": "深度求索推理模型"},
    {"id": "deepseek-v3", "name": "DeepSeek-V3", "size": "671B", "desc": "深度求索 MoE 通用模型"},
    {"id": "mistral", "name": "Mistral", "size": "7B", "desc": "Mistral AI 开源模型"},
    {"id": "mixtral", "name": "Mixtral", "size": "8x7B / 8x22B", "desc": "Mistral MoE 模型"},
    {"id": "phi3", "name": "Phi-3", "size": "3.8B / 14B", "desc": "微软小型高效模型"},
    {"id": "phi3.5", "name": "Phi-3.5", "size": "3.8B", "desc": "微软 Phi-3 升级版"},
    {"id": "gemma2", "name": "Gemma 2", "size": "2B / 9B / 27B", "desc": "Google 开源模型"},
    {"id": "gemma3", "name": "Gemma 3", "size": "1B / 12B / 27B", "desc": "Google 最新开源模型"},
    {"id": "codegemma", "name": "CodeGemma", "size": "2B / 7B", "desc": "Google 代码模型"},
    {"id": "llava", "name": "LLaVA", "size": "7B / 13B / 34B", "desc": "多模态视觉对话"},
    {"id": "nomic-embed-text", "name": "Nomic Embed Text", "size": "137M", "desc": "文本嵌入模型"},
    {"id": "mxbai-embed-large", "name": "mxbai-embed-large", "size": "334M", "desc": "文本嵌入模型"},
    {"id": "snowflake-arctic-embed", "name": "Snowflake Arctic Embed", "size": "22M → 335M", "desc": "文本嵌入"},
    {"id": "command-r", "name": "Command R", "size": "35B / 104B", "desc": "Cohere 商用模型"},
    {"id": "dolphin-mixtral", "name": "Dolphin Mixtral", "size": "8x7B", "desc": "非审查版 Mixtral"},
    {"id": "starcoder2", "name": "StarCoder2", "size": "3B / 7B / 15B", "desc": "代码生成专用"},
    {"id": "codestral", "name": "Codestral", "size": "22B", "desc": "Mistral 代码生成模型"},
]


@router.get("/library", dependencies=[Depends(require_api_token)])
async def library():
    """Ollama 官方模型库（ollama.com/library）常用模型列表，供前端选择一键拉取。"""
    return {"models": OLLAMA_LIBRARY}


@router.post("/download", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.pull_model"))])
async def download(body: dict):
    """后台下载模型（分片 + 断点续传）。返回 job_id 供前端轮询进度。

    前端下发的 body：model_key / source（默认 "auto"，自动挑选可用来源：魔搭优先、回退 HF）/ quant（精度）。
    URL 由模型目录的 (精度, 来源) 解析得到，前端不构造 URL、也不再暴露「按镜像」切换。
    """
    key = (body.get("model_key") or "").strip()
    source = (body.get("source") or "auto").strip()
    quant = (body.get("quant") or "").strip() or None
    entry = resolve_model(key)
    if entry is None:
        raise HTTPException(400, f"未知模型：{key}")
    # 解析该 (精度, 来源) 的下载 URL；source="auto" 时自动挑选可用来源。
    if quant:
        matched = next((q for q in entry["quantizations"] if q["key"] == quant), None)
        if matched is None:
            raise HTTPException(400, f"模型 {key} 不支持精度 {quant}")
        srcs = matched["sources"]
    else:
        srcs = entry["sources"]
    chosen, src = _resolve_source(srcs, source)
    if src is None or not src.get("url"):
        raise HTTPException(
            400,
            f"模型 {key}（{quant or '默认'}）在当前环境下无可用的下载来源"
            "（HF 镜像与魔搭社区均无单文件 GGUF，或该模型为需转换的 SafeTensors）。",
        )
    url = src["url"]
    # 已有进行中的同 (模型, 精度) 任务则续接，避免重复下载。
    active = manager.active_for(key, quant)
    if active is not None:
        return manager.snapshot(active)
    quant_tag = quant or entry.get("default_quant", "Q4_K_M")
    filename = f"{key}-{quant_tag}-{chosen}.gguf"
    job = manager.start(key, entry["name"], chosen, url, filename, quant_key=quant_tag)
    return manager.snapshot(job)


@router.get("/download/{job_id}", dependencies=[Depends(require_api_token)])
async def download_progress(job_id: str):
    """轮询下载/转换进度：总量 / 已下载 / 速度 / ETA / 状态（两类任务共用）。"""
    snap = _lookup_job(job_id)
    if snap is None:
        raise HTTPException(404, "下载任务不存在")
    return snap


@router.post("/download/{job_id}/cancel", dependencies=[Depends(require_api_token)])
async def download_cancel(job_id: str):
    """请求取消正在进行的下载或转换任务。

    即使任务已不存在或已完成，也返回成功（用户只是想停止/关闭，无需报错）。
    """
    if manager.cancel(job_id):
        return {"status": "cancelled", "source": "download", "job_id": job_id}
    # 任务可能已完成或不存在，对用户来说都是「没在运行了」
    return {"status": "cancelled", "source": "none", "job_id": job_id}


@router.get("/download/active/{model_key}", dependencies=[Depends(require_api_token)])
async def download_active(model_key: str, quant: str | None = None):
    """取该模型进行中的下载任务（重入向导时续接进度）。"""
    dj = manager.active_for(model_key, quant)
    if dj is not None:
        return {"active": True, **manager.snapshot(dj)}
    return {"active": False}


def _lookup_job(job_id: str) -> Optional[dict]:
    """按 job_id 在下载任务中查找并返回快照。"""
    dj = manager.get(job_id)
    if dj is not None:
        return manager.snapshot(dj)
    return None


@router.post("/upload", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.deploy_model"))])
async def upload_model(
    files: list[UploadFile] = File(...),
    name: str = Form(...),
):
    """上传 GGUF 模型文件到工作区。

    校验 GGUF 魔数，保存后返回路径。不再支持 SafeTensors（已移除转换管线）。
    """
    safe = _safe_name(name)
    if len(files) != 1:
        raise HTTPException(400, "请上传单个 GGUF 模型文件")

    f = files[0]
    head = await f.read(4)
    if head != b"GGUF":
        raise HTTPException(400, "文件不是有效的 GGUF 模型（魔数校验失败）")

    gguf_path = os.path.join(manager.workspace, safe + ".gguf")
    with open(gguf_path, "wb") as out:
        out.write(head)
        shutil.copyfileobj(f.file, out)

    size = os.path.getsize(gguf_path)
    return {"status": "ok", "path": gguf_path, "name": safe, "size": size, "format": "gguf"}


def _scan_model_dir(path: str, safe: str) -> dict:
    """扫描模型目录，返回结构化元信息：格式、文件数等。只关心 GGUF。"""
    gguf_file: str = ""
    total_size = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                pass
            if fn.endswith(".gguf") and not gguf_file:
                gguf_file = fp

    if gguf_file:
        return {"name": safe, "path": gguf_file, "size": total_size, "format": "gguf"}
    return {"name": safe, "path": path, "size": total_size, "format": "unknown"}


@router.post("/deploy", dependencies=[Depends(require_api_token), Depends(require_permission("ollama.deploy_model"))])
async def deploy(body: dict):
    """部署模型：上传 GGUF blob → 用新版 API（files + parameters）创建模型进 Ollama。

    Ollama 0.32.1+ 的 /api/create 不再支持 modelfile 字段，改为独立的
    files（文件→digest 映射）与 parameters（对象）等字段。先上传 blob，再创建。
    """
    _require_httpx()
    gguf_path = (body.get("gguf_path") or "").strip()
    name = _safe_name(body.get("name") or "")
    if not gguf_path or not os.path.exists(gguf_path):
        raise HTTPException(400, "GGUF 路径无效或文件不存在")
    if not name:
        raise HTTPException(400, "模型名称不能为空")
    deploy_params = body.get("params") or {}
    url = _base(body.get("base_url"))
    try:
        # 1) 分块计算 SHA256，控制内存占用。
        digest = _sha256_chunked(gguf_path)
        # 经网卡门面转发（localhost Ollama，回环放行）。
        # 2) 流式上传 blob（异步分块，不全部加载到内存）。
        r = await arequest(
            "POST", url + "/api/blobs/" + digest,
            content=_file_async_iter(gguf_path),
            headers={"Content-Type": "application/octet-stream"},
            timeout=600.0,
        )
        if r.status_code not in (200, 201):
            print(f"[ollama deploy] blob upload failed: {r.status_code} {r.text[:200]}", flush=True)
            raise HTTPException(502, f"blob 上传失败：{r.status_code} {r.text[:200]}")
        # 3) 创建模型（新版 API）。
        create_body: dict = {
            "model": name,
            "files": {"model.gguf": digest},
            "stream": False,
        }
        clean_params = {k: v for k, v in deploy_params.items() if v not in (None, "")}
        if clean_params:
            create_body["parameters"] = clean_params
        r2 = await arequest("POST", url + "/api/create", json=create_body, timeout=600.0)
        if r2.status_code != 200:
            logger.warning("deploy Ollama /api/create 返回 %s: %s", r2.status_code, r2.text[:500])
            raise HTTPException(502, f"模型部署失败：{r2.status_code} {r2.text[:300]}")
        return {"status": "ok", "model": name}
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(500, f"GGUF 文件读取异常：{e}")
    except Exception as e:
        raise HTTPException(502, f"部署异常：{e}")