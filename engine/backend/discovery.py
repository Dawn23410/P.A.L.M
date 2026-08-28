"""模型发现：给定提供方配置，探测连通性并拉取远端模型列表。

覆盖三种类型：
- openai_compat：GET {base_url}/models  （Authorization: Bearer <key>）
- anthropic    ：GET {base_url}/models  （x-api-key + anthropic-version）
- gemini       ：GET {base_url}/models?key=<key>  （返回 models[].name，去掉 "models/" 前缀）

成功返回模型 id 列表（连通性即视为通过）；任何网络/鉴权/解析错误都会抛出带说明的异常。
"""
from __future__ import annotations

import httpx


async def discover_models(
    provider_type: str,
    base_url: str,
    api_key: str,
    timeout: float = 12.0,
) -> list[str]:
    base = (base_url or "").rstrip("/")
    if not base:
        raise ValueError("未提供请求地址（base_url）")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider_type == "gemini":
            url = f"{base}/models"
            r = await client.get(url, params={"key": api_key or ""})
        elif provider_type == "anthropic":
            url = f"{base}/models"
            r = await client.get(
                url,
                headers={
                    "x-api-key": api_key or "",
                    "anthropic-version": "2023-06-01",
                },
            )
        else:  # openai_compat 及其它走 OpenAI 兼容约定
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
        if provider_type == "gemini":
            items = [m.get("name", "") for m in data.get("models", [])]
            return [i.split("/")[-1] for i in items if i]
        items = [m.get("id", "") for m in data.get("data", [])]
        return [i for i in items if i]
