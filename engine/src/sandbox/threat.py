"""AI 沙箱 — 威胁情报（网络层）。

对目标 host/ip 做威胁评估：私有网段识别、已知恶意域名/IP 黑名单、
可疑端口判定。供 guardrail 网络拦截裁决使用。

接口契约（被 web.py /api/net/threat 调用）：
    check(host: str, ip: str) -> dict
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict

# 永久黑名单（示例集，真实部署应从威胁情报源同步）
_BLACKLIST_IPS = {
    "0.0.0.0",
    "127.0.0.1",  # 环回，沙箱内联一般无意义
}
_BLACKLIST_DOMAINS = {
    "localhost",
    "metadata.google.internal",   # 云元数据端点
    "169.254.169.254",            # 云元数据 IP（域名形式）
}

# 高危端口（常被用于外联 C2 / 暴露服务）
_SUSPICIOUS_PORTS = {22, 23, 3389, 4444, 6667, 8443}

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETS)


def _normalize_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def check(host: str, ip: str) -> Dict[str, Any]:
    """评估目标威胁等级。

    返回字段（被 web.py 透传为 JSON）：
        level       : "safe" | "suspicious" | "malicious"
        blacklisted : bool
        private     : bool
        reason      : str
        ports_hint  : List[int] 命中的可疑端口（若能从 host 解析）
    """
    host_n = _normalize_host(host)
    ip = (ip or "").strip()

    if host_n in _BLACKLIST_DOMAINS or ip in _BLACKLIST_IPS:
        return {
            "level": "malicious",
            "blacklisted": True,
            "private": _is_private(ip),
            "reason": "目标在永久黑名单中（云元数据/环回）",
            "ports_hint": [],
        }

    if _is_private(ip):
        return {
            "level": "suspicious",
            "blacklisted": False,
            "private": True,
            "reason": "目标为内网/私有地址，可能存在横向移动风险",
            "ports_hint": [],
        }

    # host 中若带端口，检查是否可疑
    ports_hint: list[int] = []
    if ":" in host_n:
        try:
            p = int(host_n.rsplit(":", 1)[1])
            if p in _SUSPICIOUS_PORTS:
                ports_hint.append(p)
        except ValueError:
            pass

    if ports_hint:
        return {
            "level": "suspicious",
            "blacklisted": False,
            "private": False,
            "reason": "目标端口 %s 属于高危端口" % ports_hint,
            "ports_hint": ports_hint,
        }

    return {
        "level": "safe",
        "blacklisted": False,
        "private": _is_private(ip),
        "reason": "未命中已知威胁特征",
        "ports_hint": [],
    }
