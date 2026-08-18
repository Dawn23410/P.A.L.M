#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P.A.L.M 系统启动入口（主板 FastAPI 网关）。

职责（严格物理解耦 + FastAPI 通讯）：
- 发现并加载全部砖：每个砖的 `src/__init__.py` 导入即 `registry.register(brick)`，
  并自带 `router = APIRouter(...)` 作为该砖的 HTTP 面。加载逐砖容错，单砖失败不拖垮系统。
- 装配 FastAPI app：挂载每块砖的 router（砖内部经 transport 连通其引擎/子进程）、
  挂载主板自身路由（bios/hotplug 等）、提供 `/health` 与 `/api/bricks`。
- 启动事件：把已注册砖包成管理芯片（BrickHandle），按总线聚合，应用资源总帽。
  子进程砖（ipc://）的引擎由各自 launcher 按需拉起，启动期不强行拉起重计算砖。

运行：`runtime/.venv/Scripts/python.exe palm.py`（默认 127.0.0.1:8000）。
仅做装配校验：`runtime/.venv/Scripts/python.exe -c "import palm; palm.build_app()"`。
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

# 启动即加载项目根 .env（.env.example 已记录全部可配置项；python-dotenv 已随
# chromadb 装入 runtime/.venv）。不加载则 SOVITS_* 等配置无法经环境变量注入，
# 砖块会僵在 503 降级态。.env 已被 .gitignore 忽略，不会进入版本库。
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001  缺依赖/缺文件时静默降级，仍可按代码默认值启动
    pass

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 注册 `palm_bricks` 命名空间父包：加载器把每块砖当作 `palm_bricks.<pkg>` 加载，
# 子模块导入机制要求父包存在于 sys.modules，否则报 No module named 'palm_bricks'。
import types  # noqa: E402

_ns = types.ModuleType("palm_bricks")
_ns.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault("palm_bricks", _ns)

# 不扫描的顶层目录（归档/依赖/数据/运行期 venv）。
_SKIP_TOP = {
    "archive", "removed_qwentts_20260815", ".git", ".workbuddy",
    "Data", "docs", "palm_sdk", "runtime", "PALM砖块基准测试", "ollama_workspace",
}

# 递归发现砖目录时的跳过集（顶层跳过集 + 运行期 venv / 缓存 / 主板独占加载 / 归档回收站）。
_BRICK_SKIP = set(_SKIP_TOP) | {
    ".venv", ".venv-gsv", ".venv-stt", ".venv-speaker",
    "__pycache__", "node_modules", "主板", "垃圾",
}


def _safe_pkg_name(folder: str) -> str:
    """中文/带空格的砖目录名 → 合法且唯一的 python 包名。"""
    return "b_" + "".join(ch if ch.isalnum() else "_" for ch in folder)


def _load_as_package(init_path: Path, pkg_name: str):
    """把一个 `src/` 目录当作具名包加载，使其中相对导入（from .brick import ...）生效。

    关键：submodule_search_locations 指向该 src 目录，importlib 才能把
    `pkg.brick` 解析到 `src/brick.py`。
    """
    spec = importlib.util.spec_from_file_location(
        pkg_name, str(init_path),
        submodule_search_locations=[str(init_path.parent)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _iter_brick_dirs(root: Path):
    """递归找出所有含 src/__init__.py 的砖目录（位置无关、深度无关）。

    命中某砖目录（自身含 src/__init__.py）即产出，并停止下钻其内部分支——
    砖内部的子目录（如扩展卡内的引擎组件）由该砖自行加载管理，不应被当作
    独立砖重复发现。非砖目录（如总线分组文件夹 cpu/sata/...）继续下钻。
    """
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _BRICK_SKIP:
            continue
        init = entry / "src" / "__init__.py"
        if init.exists():
            yield entry
            continue
        yield from _iter_brick_dirs(entry)


def discover_bricks() -> dict[str, str]:
    """递归扫描砖目录，逐个加载其 src 包（导入即注册）。返回每块砖的加载结果。

    砖可位于 ROOT（单体布局）或 ROOT 的兄弟目录 Desktop/P.A.L.M_砖块（独立砖块布局），
    并可被任意层级的分组目录（如按总线类型 cpu/sata/...）嵌套——发现逻辑与深度无关。
    """
    results: dict[str, str] = {}
    # 砖可位于 ROOT（单体布局）、ROOT 的兄弟目录 Desktop/P.A.L.M_砖块（旧独立布局）、
    # 或 ROOT 内部的 P.A.L.M_砖块（当前布局）。三者都经 is_dir() 守卫，不存在即跳过。
    roots = [ROOT, ROOT.parent / "P.A.L.M_砖块", ROOT / "P.A.L.M_砖块"]
    for base in roots:
        if not base.is_dir():
            continue
        for d in _iter_brick_dirs(base):
            pkg = _safe_pkg_name(d.name)
            try:
                _load_as_package(d / "src" / "__init__.py", f"palm_bricks.{pkg}")
                results[d.name] = "ok"
            except Exception as exc:  # noqa: BLE001  单砖失败不影响整体
                results[d.name] = f"fail: {type(exc).__name__}: {exc}"
    return results


def _find_mainboard() -> Path | None:
    """递归查找主板目录（含 src/__init__.py），兼容单体布局与任意分组嵌套。

    主板由本函数独占加载（discover_bricks 已将其排除），避免被当作普通砖重复注册。
    """
    candidates = [ROOT, ROOT.parent / "P.A.L.M_砖块", ROOT / "P.A.L.M_砖块"]
    skip = {
        ".venv", ".venv-gsv", ".venv-stt", ".venv-speaker",
        "__pycache__", "node_modules", "Data", "archive", "垃圾",
        ".git", ".workbuddy", "palm_sdk", "runtime", "docs",
    }

    def _walk(d: Path) -> Path | None:
        for entry in sorted(d.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in skip:
                continue
            if entry.name == "主板" and (entry / "src" / "__init__.py").exists():
                return entry
            found = _walk(entry)
            if found is not None:
                return found
        return None

    for base in candidates:
        if not base.is_dir():
            continue
        found = _walk(base)
        if found is not None:
            return found
    return None


def _mount_mainboard_routers(app) -> list[str]:
    """加载主板自身路由（bios/hotplug 等），返回已挂载的路由标识。

    主板可位于 ROOT/主板、ROOT/P.A.L.M_砖块/主板 或任意分组嵌套（如 .../board/主板），
    向后兼容全部位置。
    """
    mounted: list[str] = []
    mb_dir = _find_mainboard()
    if mb_dir is None:
        return mounted
    mb_init = mb_dir / "src" / "__init__.py"
    try:
        _load_as_package(mb_init, "palm_bricks._mainboard")
    except Exception:  # noqa: BLE001
        return mounted
    mb_src = mb_dir / "src"
    for pyf in sorted(mb_src.glob("*.py")):
        if pyf.name == "__init__.py":
            continue
        modname = f"palm_bricks._mainboard.{pyf.stem}"
        try:
            mod = importlib.import_module(modname)
        except Exception:  # noqa: BLE001
            continue
        router = getattr(mod, "router", None)
        if router is not None:
            try:
                app.include_router(router)
                mounted.append(f"主板:{pyf.stem}")
            except Exception:  # noqa: BLE001
                continue
    return mounted


def build_app():
    """装配并返回 FastAPI 应用（不绑定端口，便于校验）。"""
    from fastapi import FastAPI
    from palm_sdk.bricks.base import registry

    load_report = discover_bricks()
    app = FastAPI(title="P.A.L.M", version="0.1.0")

    mounted_bricks: list[str] = []
    for name, brick in list(registry.bricks.items()):
        router = getattr(brick, "router", None)
        if router is not None:
            try:
                app.include_router(router)
                mounted_bricks.append(name)
            except Exception:  # noqa: BLE001  路由挂载失败则跳过该砖
                continue

    mounted_mainboard = _mount_mainboard_routers(app)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "bricks_registered": len(registry.bricks),
            "brick_routers_mounted": len(mounted_bricks),
            "mainboard_routers_mounted": len(mounted_mainboard),
        }

    @app.get("/api/bricks")
    def list_bricks():
        return {
            "count": len(registry.bricks),
            "bricks": [
                {
                    "name": b.manifest.name,
                    "title": b.manifest.title,
                    "bus": b.manifest.bus_type,
                    "has_router": b.router is not None,
                }
                for b in registry.bricks.values()
            ],
        }

    # 前端：单页控制台由主板 FastAPI 直接托管（同源，免跨域）。
    from fastapi.responses import FileResponse, HTMLResponse
    _frontend = ROOT / "frontend" / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def index():
        if _frontend.exists():
            return FileResponse(str(_frontend))
        return HTMLResponse("<h1>P.A.L.M</h1><p>前端未构建（frontend/index.html 缺失）</p>")

    # 启动期：把已注册砖包成管理芯片，按总线聚合并应用资源总帽。
    # 子进程砖引擎由各自 launcher 按需拉起，此处不强行启动重计算砖。
    try:
        from palm_bricks._mainboard.handle import wrap_brick, apply_default_bus_caps  # type: ignore
        from palm_sdk.bricks.base import registry as _reg
        for brick in list(_reg.bricks.values()):
            try:
                wrap_brick(brick)
            except Exception:  # noqa: BLE001
                continue
        apply_default_bus_caps()
    except Exception:  # noqa: BLE001  主板治理层缺失时降级（仍保留路由可用）
        pass

    app.state.load_report = load_report
    app.state.mounted_bricks = mounted_bricks
    app.state.mounted_mainboard = mounted_mainboard
    return app


if __name__ == "__main__":
    import uvicorn

    app = build_app()
    print(f"[P.A.L.M] 砖注册 {len(app.state.load_report)} 项，路由挂载 "
          f"{len(app.state.mounted_bricks)} 砖 + {len(app.state.mounted_mainboard)} 主板")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
