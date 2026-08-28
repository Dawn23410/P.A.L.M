"""URL / 目标威胁检测接口（可插拔）。

默认实现：本地规则库评分。
- 私有 / 保留地址段（RFC1918、回环、链路本地、多播）→ 高危（可能探测内网）
- 已知追踪 / 广告域名 → 中危
- 公网域名 → 低危
URL 沙箱（check_url）：解析完整 URL，检测内网 IP 字面量、回环、明文凭据、
可疑 TLD、同形字符（钓鱼）、追踪域名、非标准端口、超长域名等异常。
预留：set_backend() / set_url_backend() 接入外部 API 或本地规则库做风险评分。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
]

_TRACKER_HINTS = ("tracker", "analytics", "ads", "adservice", "telemetry",
                  "metrics", "beacon", "collect", "stat.", "log.", "cdn-cgi")

# 常见于钓鱼 / 垃圾站的低成本 TLD
_SUSPICIOUS_TLDS = {
    "xyz", "top", "tk", "ml", "ga", "cf", "gq", "bid", "zip", "review",
    "country", "stream", "gdn", "mom", "xin", "club", "info", "click",
    "link", "work", "ninja", "party", "trade", "accountant", "download",
    "loan", "racing", "win", "host", "rest", "science", "pw", "date",
    "wang", "tw", "cc", "su", "to", "nu", "sh", "st",
}

# 同形字符（Latin ↔ 西里尔/希腊 等看起来一样的字符）用于快速检测
# 注意：只收录西里尔/希腊等"长得像拉丁"的字符，不可混入普通拉丁字母（如 b/c），
# 否则会导致任何含 b/c 的域名被误判为同形钓鱼（严重误报）。
_HOMOGLYPH = set("адефклмнорстухђіјљњќѕћџАВЕЗКМНОРСТУХ")


def _resolve(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


class ThreatChecker:
    def __init__(self):
        self.backend: Callable[[str, str | None], tuple[int, list[str]]] | None = None
        self.url_backend: Callable[[str], dict] | None = None

    def set_backend(self, fn: Callable[[str, str | None], tuple[int, list[str]]]):
        """fn(host, ip) -> (score 0-100, reasons: list[str])"""
        self.backend = fn

    def set_url_backend(self, fn: Callable[[str], dict]):
        """fn(url) -> dict（与 check_url 返回结构一致，可覆盖本地检测）"""
        self.url_backend = fn

    def check(self, host: str, ip: str | None = None) -> dict:
        if self.backend:
            score, reasons = self.backend(host, ip)
            level = "high" if score >= 70 else ("medium" if score >= 40 else "low")
            return {"host": host, "ip": ip, "score": score,
                    "level": level, "reasons": reasons, "source": "custom"}
        return self._local_check(host, ip)

    def _local_check(self, host: str, ip: str | None) -> dict:
        reasons: list[str] = []
        score = 10
        # IP 维度
        if ip:
            try:
                addr = ipaddress.ip_address(ip)
                for net in _PRIVATE_NETS:
                    if addr in net:
                        score = 95
                        reasons.append("目标为内网/保留地址段（%s），可能探测宿主机内网" % net)
                        break
                if addr.is_loopback:
                    score = 95
                    reasons.append("目标为回环地址，可能访问宿主机服务")
            except ValueError:
                pass
        # 域名维度
        h = (host or "").lower()
        if h:
            for hint in _TRACKER_HINTS:
                if hint in h:
                    score = max(score, 55)
                    reasons.append("域名含追踪/遥测特征（%s）" % hint)
                    break
            if h.endswith(".local") or h.endswith(".internal") or h.endswith(".lan"):
                score = max(score, 90)
                reasons.append("内网域名后缀")
        if not reasons:
            reasons.append("公网域名，本地规则库未见明显风险")
        level = "high" if score >= 70 else ("medium" if score >= 40 else "low")
        return {"host": host, "ip": ip, "score": score,
                "level": level, "reasons": reasons, "source": "local"}

    # ---------------- URL 沙箱 ----------------
    def check_url(self, url: str) -> dict:
        if self.url_backend:
            return self.url_backend(url)
        return self._local_check_url(url)

    def _local_check_url(self, url: str) -> dict:
        p = urlparse(url or "")
        scheme = (p.scheme or "http").lower()
        host = (p.hostname or "").lower()
        port = p.port or (443 if scheme == "https" else 80)
        reasons: list[str] = []
        anomalies: list[str] = []
        score = 10
        ip: str | None = None

        # 1) 明文凭据
        if p.username or p.password:
            reasons.append("URL 含明文凭据 (user:pass@)，存在泄露风险")
            anomalies.append("credentials_in_url")
            score = max(score, 55)

        # 2) IP 字面量
        if host:
            try:
                addr = ipaddress.ip_address(host)
                ip = host
                for net in _PRIVATE_NETS:
                    if addr in net:
                        reasons.append("URL 直接使用内网/保留地址（%s），可能探测宿主机内网" % net)
                        anomalies.append("private_ip_literal")
                        score = 95
                        break
                if addr.is_loopback:
                    reasons.append("URL 指向回环地址，可能访问宿主机服务")
                    anomalies.append("loopback_ip")
                    score = 95
            except ValueError:
                ip = _resolve(host)

        # 3) 解析到的 IP 为内网
        if ip:
            try:
                a = ipaddress.ip_address(ip)
                for net in _PRIVATE_NETS:
                    if a in net and "private_ip_literal" not in anomalies:
                        reasons.append("域名解析到内网地址 %s" % ip)
                        anomalies.append("private_resolved")
                        score = max(score, 90)
                        break
            except ValueError:
                pass

        # 4) 内网域名后缀
        if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan"):
            reasons.append("内网域名后缀（.local/.internal/.lan）")
            anomalies.append("internal_tld")
            score = max(score, 90)

        # 5) 可疑 TLD
        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if tld in _SUSPICIOUS_TLDS:
            reasons.append("高风险 TLD（.%s，常见于钓鱼/垃圾站）" % tld)
            anomalies.append("suspicious_tld")
            score = max(score, 60)

        # 6) 同形字符（钓鱼）
        if any(ch in _HOMOGLYPH for ch in host):
            reasons.append("域名含同形字符（如西里尔字母伪装），疑似钓鱼")
            anomalies.append("homoglyph")
            score = 95

        # 7) 追踪域名
        for hint in _TRACKER_HINTS:
            if hint in host:
                reasons.append("域名含追踪/遥测特征（%s）" % hint)
                anomalies.append("tracker")
                score = max(score, 55)
                break

        # 8) 非标准端口
        std_ports = {80, 8080, 8000} if scheme == "http" else {443, 8443}
        if port not in std_ports:
            reasons.append("非标准端口 %d（%s）" % (port, scheme))
            anomalies.append("unusual_port")
            score = max(score, 45)

        # 9) 超长域名（混淆/随机）
        if len(host) > 40:
            reasons.append("域名过长（%d 字符），可能为混淆/随机域名" % len(host))
            anomalies.append("long_host")
            score = max(score, 50)

        if not reasons:
            reasons.append("未发现明显异常")
        level = "high" if score >= 70 else ("medium" if score >= 40 else "low")
        return {
            "url": url, "scheme": scheme, "host": host, "port": port,
            "resolved_ip": ip, "score": score, "level": level,
            "reasons": reasons, "anomalies": anomalies, "source": "local",
        }


_DEFAULT = ThreatChecker()


def check(host: str, ip: str | None = None) -> dict:
    return _DEFAULT.check(host, ip)


def check_url(url: str) -> dict:
    return _DEFAULT.check_url(url)


def set_backend(fn):
    _DEFAULT.set_backend(fn)


def set_url_backend(fn):
    _DEFAULT.set_url_backend(fn)
