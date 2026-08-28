"""
P.A.L.M · 模块管理 API 服务
=============================
FastAPI 后端，提供模块全生命周期管理的 RESTful API。
严格遵循 MODULE_PACKAGE_SPEC.md 规范。

运行: uvicorn manager.app:app --host 0.0.0.0 --port 9090 --reload
"""

import os
import sys
import tempfile
from pathlib import Path

# 确保项目根在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from manager.module_manager import get_manager, MODULES_DIR, PACKAGES_DIR

# ─── FastAPI 应用 ────────────────────────────────────────────────

app = FastAPI(
    title="P.A.L.M Module Manager",
    description="模块包全生命周期管理 API — 符合 MODULE_PACKAGE_SPEC.md 规范",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 请求模型 ────────────────────────────────────────────────────

class InstallRequest(BaseModel):
    filename: str


class UninstallRequest(BaseModel):
    name: str


class StartRequest(BaseModel):
    name: str


class StopRequest(BaseModel):
    name: str


# ─── 健康检查 ────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "palm-module-manager", "version": "1.0.0"}


@app.get("/api/config")
def get_config():
    """返回项目路径配置"""
    return {
        "modules_dir": str(MODULES_DIR.resolve()),
        "packages_dir": str(PACKAGES_DIR.resolve()),
    }


# ─── 包管理 ──────────────────────────────────────────────────────

@app.get("/api/packages")
def list_packages():
    """列出 packages/ 下所有待安装的 .7z 包"""
    mgr = get_manager()
    return {"packages": mgr.list_packages()}


@app.delete("/api/packages/{filename}")
def delete_package(filename: str):
    """删除 packages/ 下的 .7z 包文件"""
    mgr = get_manager()
    result = mgr.delete_package(filename)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


# ─── 模块管理（CRUD） ───────────────────────────────────────────

@app.get("/api/modules")
def list_modules():
    """列出所有已安装模块及其运行状态"""
    mgr = get_manager()
    modules = mgr.get_modules()
    online = sum(1 for m in modules if m["status"] == "running")
    return {
        "modules": modules,
        "summary": {
            "total": len(modules),
            "running": online,
            "stopped": len(modules) - online,
        },
    }


@app.get("/api/modules/with-status")
def list_modules_with_status():
    """列出所有模块状态（含未安装的包 + 完整性检测）"""
    mgr = get_manager()
    modules = mgr.get_modules_with_status()
    counts = {"未安装": 0, "已安装": 0, "损坏": 0}
    for m in modules:
        s = m["status"]
        if s in counts:
            counts[s] += 1
    return {"modules": modules, "summary": counts}


@app.get("/api/modules/integrity")
def check_all_integrity():
    """对所有已安装模块执行完整性检测"""
    mgr = get_manager()
    results = []
    for s in mgr.get_modules():
        results.append(mgr.check_integrity(s["name"]))
    return {"results": results}


@app.get("/api/module/{name}")
def get_module(name: str):
    """获取单个模块的完整详情"""
    mgr = get_manager()
    mod = mgr.get_module(name)
    if mod is None:
        raise HTTPException(status_code=404, detail=f"模块 '{name}' 未找到")
    return mod


@app.post("/api/module/validate")
async def validate_package(file: UploadFile = File(...)):
    """
    上传并验证一个 .7z 模块包。
    读取包内 MANIFEST.json，按规范校验所有字段。
    验证后自动清理临时文件。
    """
    if not file.filename or not file.filename.endswith(".7z"):
        raise HTTPException(status_code=400, detail={"success": False, "error": "仅支持 .7z 文件"})

    # 保存到临时位置
    tmp = Path(tempfile.mkdtemp(prefix="palm_upload_")) / file.filename
    try:
        content = await file.read()
        tmp.write_bytes(content)

        mgr = get_manager()
        result = mgr.validate_package(tmp)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result)
        return result
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        tmp.parent.exists() and Path(tmp.parent).rmdir() if tmp.parent.exists() else None


@app.post("/api/module/install")
def install_module(req: InstallRequest):
    """
    安装模块：6步链路
    解压 → 验证 MANIFEST → 校验 → 检查依赖 → postInstall → 注册
    """
    mgr = get_manager()
    result = mgr.install(req.filename)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/module/uninstall")
def uninstall_module(req: UninstallRequest):
    """
    卸载模块：停止 → preUninstall → 清理目录 → 移除注册
    """
    mgr = get_manager()
    result = mgr.uninstall(req.name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


# ─── 模块生命周期控制 ───────────────────────────────────────────

@app.post("/api/module/start")
def start_module(req: StartRequest):
    """启动指定模块"""
    mgr = get_manager()
    result = mgr.start(req.name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/module/stop")
def stop_module(req: StopRequest):
    """停止指定模块"""
    mgr = get_manager()
    result = mgr.stop(req.name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/module/start-all")
def start_all_modules():
    """启动所有已安装模块"""
    mgr = get_manager()
    results = mgr.start_all()
    return {"success": True, "results": results}


@app.post("/api/module/stop-all")
def stop_all_modules():
    """停止所有运行中的模块"""
    mgr = get_manager()
    modules = mgr.get_modules()
    results = []
    for m in modules:
        if m["status"] == "running":
            result = mgr.stop(m["name"])
            results.append({"module": m["name"], "success": result["success"]})
    return {"success": True, "results": results}
