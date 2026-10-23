"""模型发现服务（收敛自 models 砖 brick 的 discover 部分）。

给定供应商类型与连接信息拉取模型清单：OpenAI 兼容（GET {base_url}/models）
与 Anthropic 原生（GET {base_url}/v1/models）两种列表协议。
出网统一经网卡门面（palm._core.net），默认拒绝未授权主机。
"""
from __future__ import annotations

from palm._core.logging import get_logger
from palm._core.net import arequest

logger = get_logger(__name__)


async def _list_openai(base_url: str, api_key: str) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await arequest("GET", f"{base_url}/models", headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"list {resp.status_code}: {resp.text[:300]}")
    items = (resp.json() or {}).get("data") or []
    return [m["id"] for m in items if isinstance(m, dict) and "id" in m]


async def _list_anthropic(base_url: str, api_key: str) -> list[str]:
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    resp = await arequest("GET", f"{base_url}/v1/models", headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"list {resp.status_code}: {resp.text[:300]}")
    items = (resp.json() or {}).get("models", [])
    return [m["id"] for m in items if isinstance(m, dict) and "id" in m]


async def discover_models(base_url: str, api_key: str, provider: str = "",
                          mode: str = "") -> list[dict]:
    """发现模型列表；返回 [{"id": ...}, ...]。

    mode 由调用方按供应商推导（anthropic 走原生，其余走 OpenAI 兼容）。
    """
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        raise ValueError("请求地址（base_url）不能为空")
    mode = mode or ("anthropic" if provider == "anthropic" else "openai")
    try:
        if mode == "anthropic":
            ids = await _list_anthropic(base_url, api_key)
        else:
            ids = await _list_openai(base_url, api_key)
    except Exception as exc:  # noqa: BLE001 上游错误统一转为业务异常
        raise RuntimeError(f"获取模型列表失败：{type(exc).__name__}: {exc}") from exc
    return [{"id": i} for i in ids]
