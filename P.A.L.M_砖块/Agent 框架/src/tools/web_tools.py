"""网络/搜索类工具（保留受离线管控、结构化返回的核心网络原语）。

M7 修复：关闭 httpx 自动重定向，改为有限跳数手动跟随，且每跳校验目标主机
不得为私有/环回/链路本地/保留地址，阻断 SSRF 打内网元数据服务（如 169.254.169.254）。
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import quote, urlparse

from palm_sdk.net import arequest, NetResponse

from ..tool_base import Tool

_MAX_REDIRECTS = 5


def _is_safe_host(url: str) -> bool:
    """目标主机解析后不得为私有/环回/链路本地/保留/组播地址，防 SSRF 打内网。"""
    host = urlparse(url).hostname
    if not host:
        return False
    candidates: set[str] = set()
    if host.replace(".", "").isdigit() or ":" in host:  # IP 字面量
        candidates.add(host)
    else:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        candidates.update(info[4][0] for info in infos)
    for ip_str in candidates:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    return True


async def _safe_http_get(url: str, timeout: int) -> NetResponse:
    """安全 GET：关闭自动重定向，手动有限跳数跟随，每跳校验主机非内网。

    实际收发经网卡门面（arequest）。SSRF 主机校验由本砖前置把关（解析 DNS
    后拦截私有/环回/链路本地/保留/组播地址）；网卡执行器再提供纵深防御：
    回环放行 + 外网按策略默认拒绝（未 allow_host 一律 deny），未经允许的
    内网地址同样无法出网。
    """
    if not _is_safe_host(url):
        raise RuntimeError("目标地址为内网/保留地址，已阻止（SSRF 防护）")
    headers = {"User-Agent": "PALM-Agent/1.0"}
    resp = await arequest("GET", url, headers=headers, timeout=timeout, follow_redirects=False)
    hops = 0
    while resp.status_code in (301, 302, 303, 307, 308) and hops < _MAX_REDIRECTS:
        location = resp.headers.get("location")
        if not location or not _is_safe_host(location):
            raise RuntimeError("重定向目标为内网/保留地址，已阻止（SSRF 防护）")
        resp = await arequest("GET", location, headers=headers, timeout=timeout, follow_redirects=False)
        hops += 1
    return resp


def _html_to_text(html: str, limit: int = 6000) -> str:
    """剔除脚本/样式、标签转空格、压缩空白，保留可读正文（用于 web_fetch）。"""
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]


def _extract_search_results(html: str, max_results: int = 6) -> list[dict]:
    """从 Bing 搜索结果页抽取标题/链接/摘要，剔除相对链接与无效协议。"""
    results: list[dict] = []
    # Bing 结果项类名常带后缀（如 b_algo b_algo_se），用 [^"]* 容忍附加类，避免精确匹配失效。
    blocks = re.findall(r'<li class="b_algo[^"]*".*?</li>', html, flags=re.DOTALL | re.IGNORECASE)
    for block in blocks:
        href = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"', block, flags=re.IGNORECASE)
        if not href or not re.match(r'https?://', href.group(1), re.IGNORECASE):
            continue
        title = re.search(r'<h2[^>]*>\s*<a[^>]*>(.*?)</a>', block, flags=re.DOTALL | re.IGNORECASE)
        snippet = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.DOTALL | re.IGNORECASE)
        results.append({
            "title": re.sub(r'<[^>]+>', '', title.group(1)).strip() if title else '',
            "url": href.group(1),
            "snippet": re.sub(r'<[^>]+>', '', snippet.group(1)).strip() if snippet else '',
        })
        if len(results) >= max_results:
            break
    return results


class WebSearchTool(Tool):
    @property
    def name(self) -> str: return "web_search"
    @property
    def description(self) -> str: return (
        "搜索互联网信息，返回前若干条结果的标题、链接与摘要，"
        "便于进一步用 web_fetch 抓取详情。")
    @property
    def event_type(self) -> str: return "network.request"
    @property
    def tool_permission(self) -> str: return "network.http_outbound"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        }, "required": ["query"]}
    async def execute(self, query: str) -> str:
        try:
            r = await _safe_http_get(
                f"https://www.bing.com/search?q={quote(query)}&setlang=zh-CN&cc=CN", 15)
            r.raise_for_status()
            results = _extract_search_results(r.text)
            if not results:
                return f"未找到与「{query}」相关的搜索结果。"
            lines = [f"搜索「{query}」得到 {len(results)} 条结果："]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
            return "\n".join(lines)
        except Exception as e:
            return f"搜索失败: {e}"


class WebFetchTool(Tool):
    @property
    def name(self) -> str: return "web_fetch"
    @property
    def description(self) -> str: return "获取并提取网页正文文本（已去除脚本/样式等噪声）"
    @property
    def event_type(self) -> str: return "network.request"
    @property
    def tool_permission(self) -> str: return "network.http_outbound"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {
            "url": {"type": "string", "description": "目标网页地址"},
        }, "required": ["url"]}
    async def execute(self, url: str) -> str:
        try:
            r = await _safe_http_get(url, 30)
            r.raise_for_status()
            return _html_to_text(r.text) if '<' in r.text[:200] else r.text[:6000]
        except Exception as e:
            return f"抓取失败: {e}"


WEB_TOOLS = [WebSearchTool, WebFetchTool]
