"""模型发现：给定提供方配置，探测连通性并拉取远端模型列表。

按 `provider_type` 分四条端点：

- `ollama` —— 原生 `GET {base_url}/api/tags`，取 `models[].name`
  （原生根地址下没有 `/models`；填了 `/v1` 的旧配置会被自动剥掉）。
- `anthropic` —— 原生 `GET {base_url}/v1/models`，取 `data[].id`
  （鉴权是 `x-api-key` + `anthropic-version`，**不是** Bearer）。
- `gemini` —— 原生 `GET {base_url}/v1beta/models`，取 `models[].name`（形如 `models/gemini-…`，
  回传时剥掉前缀）；鉴权是 `x-goog-api-key`。
- 其余 —— OpenAI 兼容 `GET {base_url}/models`（Authorization: Bearer <key>），
  取 `data[].id`。

成功返回模型 id 列表（连通性即视为通过）；任何网络/鉴权/解析错误都会抛出带说明的异常。
"""
from __future__ import annotations

import httpx

from ..providers.anthropic import NATIVE_VERSION


def _normalize_base(provider_type: str, base_url: str) -> str:
    """归一 base：原生通道走根地址（剥掉误写的 /v1、/v1/messages、/v1beta/…）。"""
    base = (base_url or "").rstrip("/")
    if provider_type not in ("ollama", "anthropic", "gemini", "google"):
        return base
    for suffix in ("/v1/messages", "/v1beta/models", "/v1beta", "/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    return base


async def discover_models(
    provider_type: str,
    base_url: str,
    api_key: str,
    timeout: float = 12.0,
) -> list[str]:
    base = _normalize_base(provider_type or "", base_url)
    if not base:
        raise ValueError("未提供请求地址（base_url）")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider_type == "ollama":
            return await _discover_ollama(client, base)
        if provider_type == "anthropic":
            return await _discover_anthropic(client, base, api_key)
        if provider_type in ("gemini", "google"):
            return await _discover_gemini(client, base, api_key)

        # 其余统一走 OpenAI 兼容约定（provider_type 仅作提示用，不再分支协议）
        url = f"{base}/models"
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {api_key or ''}"},
        )

        # 先给出可读错误（含状态码），便于用户判断是地址还是密钥问题
        if r.status_code == 401:
            raise ValueError("鉴权失败（401）：API Key 可能无效。")
        if r.status_code == 404:
            raise ValueError(
                "返回 404：请求地址可能缺少 /v1 等路径，或该端点不提供 /models。"
            )
        r.raise_for_status()

        data = r.json()
        items = [m.get("id", "") for m in data.get("data", [])]
        return [i for i in items if i]


async def _get_models(
    client: httpx.AsyncClient, base: str, path: str, headers: dict,
    *, list_key: str, id_key: str, transform=None,
    auth_codes: tuple = (), auth_msg: str | None = None,
    notfound_msg: str | None = None, connect_msg: str | None = None,
) -> list[str]:
    """原生通道通用的「GET 模型列表 → 解析 id」骨架。

    三个原生协议（ollama / anthropic / gemini）的列表发现**逻辑骨架完全一致**
    （GET → 捕获传输错误 → 状态码判定 → 取 id），差异只在于路径、鉴权头、JSON 里的
    列表/主键字段名、以及是否剥前缀（Gemini 的 `models/gemini-…`）。这些差异全部由
    参数表达；**状态码文案逐字保留**（用户看到的报错措辞不能因重构改变）。

    `connect_msg` 是 `.format(base=, type_name=)` 模板（在抛错时求值异常类名），
    不传则走统一默认措辞。
    """
    url = f"{base}{path}"
    try:
        r = await client.get(url, headers=headers)
    except httpx.TransportError as e:
        tname = type(e).__name__
        msg = connect_msg.format(base=base, type_name=tname) if connect_msg \
              else f"无法连接（{base}）：{tname}"
        raise ValueError(msg) from e
    if r.status_code in auth_codes and auth_msg:
        raise ValueError(auth_msg)
    if r.status_code == 404 and notfound_msg:
        raise ValueError(notfound_msg)
    r.raise_for_status()
    out = []
    for m in (r.json().get(list_key) or []):
        name = (m.get(id_key) or "")
        name = transform(name) if transform else name
        if name:
            out.append(name)
    return out


async def _discover_ollama(client: httpx.AsyncClient, base: str) -> list[str]:
    """Ollama 原生模型列表：GET /api/tags → models[].name。"""
    return await _get_models(
        client, base, "/api/tags", {},
        list_key="models", id_key="name",
        connect_msg="无法连接 Ollama（{base}）：{type_name}，请确认服务已启动。",
        notfound_msg=(
            f"返回 404：{base} 看起来不是 Ollama 原生地址"
            "（原生协议要求根地址，不带 /v1）。"
        ),
    )


async def _discover_anthropic(client: httpx.AsyncClient, base: str, api_key: str) -> list[str]:
    """Anthropic 原生模型列表：GET /v1/models（x-api-key + anthropic-version）。"""
    return await _get_models(
        client, base, "/v1/models",
        {"x-api-key": api_key or "", "anthropic-version": NATIVE_VERSION},
        list_key="data", id_key="id",
        auth_codes=(401,),
        auth_msg="鉴权失败（401）：API Key 可能无效。",
        notfound_msg=(
            f"返回 404：{base}/v1/models 不存在。原生协议要求 base_url 填站点根地址"
            "（如 https://api.anthropic.com），不带 /v1。"
        ),
    )


async def _discover_gemini(client: httpx.AsyncClient, base: str, api_key: str) -> list[str]:
    """Gemini 原生模型列表：GET /v1beta/models（x-goog-api-key）。

    返回的 `name` 形如 `models/gemini-2.5-flash`，调用方要用的是末段，故在此剥掉前缀。
    """
    return await _get_models(
        client, base, "/v1beta/models",
        {"x-goog-api-key": api_key or ""},
        list_key="models", id_key="name", transform=lambda n: n.split("/")[-1],
        auth_codes=(401, 403),
        auth_msg="鉴权失败：API Key 可能无效（原生协议用 x-goog-api-key）。",
        notfound_msg=(
            f"返回 404：{base}/v1beta/models 不存在。原生协议要求 base_url 填站点根地址"
            "（如 https://generativelanguage.googleapis.com），不带 /v1beta。"
        ),
    )
