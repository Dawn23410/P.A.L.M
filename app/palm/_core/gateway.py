# 离线网关：统一委托网卡门面（palm_sdk.net）为离线唯一真相源。
# 离线限制的真实实现与判定都在 palm_sdk.net（由网卡砖持有），本层仅作兼容外壳，
# 避免旧调用方（离线砖、沙箱工具）崩溃；新代码应直接 import palm_sdk.net。
from palm._core.net import is_offline, set_offline  # noqa: F401


def patch_httpx(*_args, **_kwargs) -> None:
    """历史兼容：运行时拦截已迁移至 palm_sdk.net.install_guard（由网卡砖安装）。
    此处保留空实现，避免旧调用方崩溃；离线开关改用 palm_sdk.net.set_offline。"""
    return None
