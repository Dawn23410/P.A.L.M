"""对话调度：组装消息、调用 provider、流式输出、落盘。"""
from __future__ import annotations

import asyncio

import base64
import mimetypes
import time
from typing import AsyncIterator, Optional

from .config import UPLOAD_DIR, get_provider, load_config
from .metrics import record_request
from .models import ChatRequest, Message, ModelParameters, ProviderConfig
from ..obs import get_request_id, log_event, set_request_id
from ..providers import get_provider_instance
from . import storage


def resolve_image(url: Optional[str], default_mime: str = "image/png") -> str:
    """将本地上传路径 (/uploads/xxx) 转换为自包含的 data URI，便于模型 API 直接读取。

    `default_mime` 只在扩展名认不出类型时兜底 —— 文档附件要传 `application/pdf` 之类，
    不能沿用图片的 `image/png`（否则能力矩阵会把它当图片走视觉闸门）。
    """
    if url and url.startswith("/uploads/"):
        path = UPLOAD_DIR / url[len("/uploads/"):]
        if path.exists():
            mime = mimetypes.guess_type(str(path))[0] or default_mime
            b64 = base64.b64encode(path.read_bytes()).decode()
            return f"data:{mime};base64,{b64}"
    return url or ""


async def prewarm_active_provider() -> Optional[float]:
    """预热 active provider 的连接（把 TCP+TLS 握手移出用户首问的关键路径）。

    WebUI / CLI 启动时调用。返回预热耗时 ms；无可用 provider 时返回 None。
    兼容说明：mock provider 已移除，但旧 config.json 可能残留 type="mock" 条目，
    此处跳过其预热（该条目经工厂回退为 openai_compat，预热其空 base_url 无意义）。
    """
    cfg = load_config()
    pcfg = get_provider(cfg.active_provider)
    if pcfg is None or pcfg.type == "mock":
        return None
    return await get_provider_instance(pcfg.to_kernel()).prewarm()


async def run_chat(req: ChatRequest) -> AsyncIterator[dict]:
    """执行一次流式对话，产出 SSE 事件字典并持久化消息。"""
    # 回合边界种下 request_id：provider 的重试/错误日志都挂在这一条上，便于按请求排障
    set_request_id(None)
    request_id = get_request_id()
    cfg = load_config()

    # 1. 解析 provider / model / 参数
    provider_cfg = get_provider(req.provider) or get_provider(cfg.active_provider)

    # 1.4 未配置任何 provider 但携带请求级端点/KEY → 凭请求构造（零配置直连）
    if provider_cfg is None and (req.base_url or req.api_key):
        provider_cfg = ProviderConfig(
            id="__request__", name="__request__",
            type=req.provider_type or "openai_compat",
            base_url=req.base_url or "", api_key=req.api_key or "",
            models=[req.model] if req.model else [])

    if provider_cfg is None:
        yield {"type": "error", "message": "未配置有效的模型提供方，请在设置中添加。"}
        return
    model = req.model or cfg.active_model or ""
    if not model:
        yield {"type": "error", "message": "未指定模型，请在设置中选择。"}
        return

    # 1.5 请求级端点/KEY 覆盖：每次 API 传输可携带，优先级高于 config.json，不落盘
    if req.base_url or req.api_key:
        provider_cfg = provider_cfg.model_copy(deep=True)
        if req.base_url:
            provider_cfg.base_url = req.base_url
        if req.api_key:
            provider_cfg.api_key = req.api_key
    params: ModelParameters = req.parameters or cfg.parameters
    system_prompt = req.system_prompt if req.system_prompt is not None else cfg.system_prompt

    # 2. 获取/创建会话
    if req.conversation_id:
        conv = await asyncio.to_thread(storage.get_conversation, req.conversation_id)
        if conv is None:
            conv = await asyncio.to_thread(storage.create_conversation)
    else:
        conv = await asyncio.to_thread(storage.create_conversation)

    # 先告知前端会话 id（新建会话时需要）
    yield {"type": "meta", "conversation_id": conv.id, "title": conv.title}

    # 3. 追加用户消息并持久化
    user_msg = Message(role="user", content=req.content, images=req.images,
                       files=req.files, ts=time.time())
    # append_message 会重新从磁盘读取并写回；用其返回值刷新内存中的 conv，
    # 否则新建会话的首条用户消息不会进入后续组装的 messages（影响模型上下文）。
    conv = (await asyncio.to_thread(storage.append_message, conv.id, user_msg)) or conv

    # 4. 组装完整消息（动态注入系统提示词，并将本地图片转为 data URI）
    msgs: list[Message] = []
    if system_prompt:
        msgs.append(Message(role="system", content=system_prompt))
    for m in conv.messages:
        msgs.append(_replay(m))

    # 5. 调用 provider 流式生成（+ 开销监控埋点）
    provider = get_provider_instance(provider_cfg.to_kernel())
    accumulated = ""
    reasoning_acc = ""
    reasoning_echo: str | None = None    # 原生思考块凭据（下一轮原样回传，勿解析）
    tool_calls_acc: list | None = None   # 本次回复的原生工具调用（多轮 Tool 需回写会话）
    t_req = time.perf_counter()
    req_ok = True
    completion_tokens: int | None = None
    try:
        k_msgs = [mm.to_kernel() for mm in msgs]
        k_params = params.to_kernel()
        async for chunk in provider.complete(k_msgs, k_params, model, stream=True):
            if "reasoning" in chunk:
                reasoning_acc += chunk["reasoning"]
                yield {"type": "reasoning", "content": chunk["reasoning"]}
            elif "content" in chunk:
                accumulated += chunk["content"]
                yield {"type": "token", "content": chunk["content"]}
            elif "tool_call_delta" in chunk:
                # 工具调用开始：拿到名字即下发，供前端实时显示"正在调用 X"
                yield {"type": "tool_call_delta", **chunk["tool_call_delta"]}
            elif "tool_calls" in chunk:
                # 完整工具调用（arguments 已由 provider 拼接成合法 JSON 字符串）
                tool_calls_acc = chunk["tool_calls"]
                yield {"type": "tool_calls", "tool_calls": tool_calls_acc}
            elif chunk.get("done"):
                usage = chunk.get("usage", {})
                # stats 为回传拆分器归一后的统一字段（缓存命中/TTFT/输出速度等）；
                # provider 未提供时透传 None，前端自行降级显示
                stats = chunk.get("stats")
                reasoning_echo = (stats or {}).get("extra", {}).get("native_blocks")
                completion_tokens = (stats or {}).get("output_tokens") or usage.get("completion_tokens")
                yield {"type": "done", "usage": usage, "stats": stats}
    except Exception as e:  # 捕获所有异常，转为前端可显示的错误
        req_ok = False
        log_event("chat.turn.error", level="error", provider=provider.name, model=model,
                  error=type(e).__name__,
                  retryable=bool(getattr(e, "retryable", False)),
                  msg=(str(e) or type(e).__name__)[:200])
        # 空消息异常兜底（如 httpx.ReadTimeout() str 为空）：至少给出异常类型名。
        # error_type / retryable / request_id 为**附加**字段，前端可据 retryable 决定
        # 要不要提示"重试"（限流/超时值得重试，参数错/鉴权错不该重试）。
        yield {"type": "error", "message": str(e) or type(e).__name__,
               "error_type": type(e).__name__,
               "retryable": bool(getattr(e, "retryable", False)),
               "request_id": request_id}
        return
    finally:
        record_request(provider.name, (time.perf_counter() - t_req) * 1000,
                       req_ok, completion_tokens)
    log_event("chat.turn.done", level="info", provider=provider.name, model=model,
              ms=round((time.perf_counter() - t_req) * 1000, 1),
              tokens=completion_tokens)

    # 6. 落盘助手回复（含思维链与回传凭据，便于后续查看/导出与下一轮原样回传）
    await asyncio.to_thread(
        storage.append_message,
        conv.id,
        Message(role="assistant", content=accumulated, reasoning=reasoning_acc or None,
                reasoning_echo=reasoning_echo, tool_calls=tool_calls_acc, ts=time.time()),
    )
    yield {"type": "meta", "conversation_id": conv.id, "title": conv.title, "finished": True}


def _resolve_file(f):
    """文档附件解析：dict 形态原样透传（调用方已自带 mime/data），字符串才做路径解析。"""
    return f if isinstance(f, dict) else (resolve_image(f, "application/pdf") or f)


def _replay(m: Message) -> Message:
    """历史消息 → 本次请求的入参消息（把本地图片/文档换成 data URI）。

    必须**整条**搬运：工具轮次（tool_calls / tool_call_id / name / tool_error）与思考块
    凭据少一个都会被服务端判为非法请求 —— 前者缺 tool 响应、后者缺思考块签名。
    """
    images = [resolve_image(i) for i in (m.images or [])] if m.images else None
    files = [_resolve_file(f) for f in (m.files or [])] if m.files else None
    return Message(role=m.role, content=m.content, images=images, files=files, ts=m.ts,
                   reasoning=m.reasoning, reasoning_echo=m.reasoning_echo,
                   tool_calls=m.tool_calls, tool_call_id=m.tool_call_id, name=m.name,
                   tool_error=m.tool_error)
