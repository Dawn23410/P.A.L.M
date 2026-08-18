"""砖包加载器：把任意 src/ 目录当作具名包导入（与主板发现逻辑同构）。

容器砖（如扩展卡）用它把内部组件砖加载进来——导入即触发组件 src/__init__.py
里的 registry.register，使组件能力进入全局 registry，容器砖随后经 registry.get
取到句柄并对外统一暴露。

该工具属于 palm_sdk 基座层：砖不得反向 import 主板（palm.py），故容器砖复用本工具
管理内部组件，而非依赖主板发现逻辑。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .base import Brick


def _safe_pkg_name(folder: str) -> str:
    """中文/带空格的砖目录名 → 合法且唯一的 python 包名。"""
    return "b_" + "".join(ch if ch.isalnum() else "_" for ch in folder)


def load_brick_package(src_dir: str | Path, pkg_name: str | None = None) -> Brick | None:
    """加载砖的 src 包（导入即触发注册），返回其 Brick 实例或 None。

    src_dir 指向含 __init__.py 的 src 目录；pkg_name 为导入用的全局唯一包名，
    缺省由父目录名推导。返回模块导出的 Brick（若 __init__ 形如 `from .brick import
    brick`）；若砖以 `from . import brick`（brick 为子模块）方式注册，则因导入已
    触发 registry.register，本函数返回 None，调用方应改经 registry.get(组件名) 取句柄。
    """
    src_dir = Path(src_dir)
    init = src_dir / "__init__.py"
    if not init.exists():
        raise FileNotFoundError(f"砖包缺失 __init__.py: {init}")
    if pkg_name is None:
        pkg_name = _safe_pkg_name(src_dir.parent.name)
    if pkg_name in sys.modules:
        mod = sys.modules[pkg_name]
    else:
        spec = importlib.util.spec_from_file_location(
            pkg_name, str(init),
            submodule_search_locations=[str(src_dir)],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = mod
        spec.loader.exec_module(mod)
    brick = getattr(mod, "brick", None)
    if isinstance(brick, Brick):
        return brick
    # 兼容 `from . import brick`（brick 是子模块）的砖：注册已发生，返回 None 由调用方取 registry。
    return None
