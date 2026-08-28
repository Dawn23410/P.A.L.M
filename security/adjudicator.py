#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沙箱网络裁决引擎 (sandbox_adjudicator.py)

严格按用户保存的裁决规范实现：单请求 JSON -> 单裁决 JSON，无额外文字。
9 条规则分四阶段，严格顺序执行，命中即停。

输入 (硬性单数):
  target_ip: str
  port: int
  method: str
  path: str
  body_preview: str
  is_private_ip: bool
  request_rate_per_minute: int

输出 (硬性单数):
  {"action": "ALLOW"|"DENY"|"HUMAN_REQUIRED",
   "confidence": float,
   "reason": str}   # <=25 字，须注明最高优先级规则编号+核心原因

设计目标：标准库零依赖、跨平台、mypy --strict 友好、可单测、可做 LLM 兜底前端。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Literal

Action = Literal["ALLOW", "DENY", "HUMAN_REQUIRED"]

# 阶段一：内网常见网关地址（"等常见网关" 用 .1 尾号启发式兜底）
_GATEWAY_IPS: frozenset[str] = frozenset({
    "192.168.1.1", "192.168.0.1", "10.0.0.1", "192.168.31.1",
    "192.168.2.1", "10.0.0.138", "172.16.0.1", "192.168.8.1",
})
_GATEWAY_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.1$")

_HIGH_RISK_PORTS: frozenset[int] = frozenset({22, 23, 445, 3306, 3389, 5900})

_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "DELETE", "PATCH"})

# 阶段一/三敏感路径词
_SENSITIVE_PATH_TOKENS: tuple[str, ...] = (
    "/config", "/setup", "/restore", "/reboot",
    "/firmware", "/goform", "/cgi-bin",
)
# 阶段二安全诊断路径词
_DIAG_PATH_TOKENS: tuple[str, ...] = ("/status", "/health", "/ping", "/info")

_LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_gateway(ip: str) -> bool:
    if ip in _GATEWAY_IPS:
        return True
    # 先排除环回地址（127.0.0.0/8、::1）
    _LOOPBACK_PREFIXES = ("127.", "::1")
    if ip.startswith(_LOOPBACK_PREFIXES):
        return False
    # 私有网段 .1 尾号常见网关启发式
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return bool(_GATEWAY_RE.match(ip or ""))
    if not addr.is_private:
        return False
    return (ip or "").endswith(".1")


def _path_has(path: str, tokens: tuple[str, ...]) -> bool:
    p = (path or "").lower()
    return any(tok in p for tok in tokens)


def _norm_method(method: str) -> str:
    return (method or "").upper().strip()


def adjudicate(req: Dict[str, Any]) -> Dict[str, Any]:
    """对单个网络请求做严格顺序裁决，返回单数裁决 JSON。

    规则命中顺序固定：阶段一(1,2,3) -> 阶段二(4,5) -> 阶段三(6,7,8) -> 阶段四(9)。
    """
    target_ip = str(req.get("target_ip", "") or "")
    port = int(req.get("port", 0) or 0)
    method = _norm_method(str(req.get("method", "") or ""))
    path = str(req.get("path", "") or "")
    is_private_ip = bool(req.get("is_private_ip", False))
    try:
        rate = int(req.get("request_rate_per_minute", 0) or 0)
    except (TypeError, ValueError):
        rate = 0

    # ---- 阶段一：硬否决 ----
    # 规则 1：网关写入
    if _is_gateway(target_ip) and method in _WRITE_METHODS:
        return {"action": "DENY", "confidence": 1.0,
                "reason": "规则1-网关写入操作（%s:%d）" % (target_ip, port)}
    # 规则 2：高危端口
    if port in _HIGH_RISK_PORTS:
        return {"action": "DENY", "confidence": 1.0,
                "reason": "规则2-高危管理端口（%d）" % port}
    # 规则 3：敏感路径写入
    if method in _WRITE_METHODS and _path_has(path, _SENSITIVE_PATH_TOKENS):
        return {"action": "DENY", "confidence": 0.99,
                "reason": "规则3-敏感路径写入操作"}

    # ---- 阶段二：明确放行 ----
    # 规则 4：本地环回
    if target_ip in _LOOPBACK:
        return {"action": "ALLOW", "confidence": 1.0,
                "reason": "规则4-本地环回信任"}
    # 规则 5：安全诊断读取
    if (method == "GET" and port in (80, 443, 8080)
            and _path_has(path, _DIAG_PATH_TOKENS)):
        return {"action": "ALLOW", "confidence": 0.98,
                "reason": "规则5-安全状态读取"}

    # ---- 阶段三：边界与降级 ----
    # 规则 6：只读敏感
    if method == "GET" and _path_has(path, _SENSITIVE_PATH_TOKENS):
        return {"action": "HUMAN_REQUIRED", "confidence": 0.80,
                "reason": "规则6-读取敏感配置，建议审计"}
    # 规则 7：高频探测熔断
    if rate > 20:
        return {"action": "DENY", "confidence": 0.99,
                "reason": "规则7-高频内网探测（熔断）"}
    # 规则 8：未知内网
    if is_private_ip:
        return {"action": "HUMAN_REQUIRED", "confidence": 0.60,
                "reason": "规则8-未知内网设备请求"}

    # ---- 阶段四：公网兜底 ----
    return {"action": "HUMAN_REQUIRED", "confidence": 0.50,
            "reason": "规则9-公网非标请求，需确认"}


def adjudicate_batch(reqs: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """批量裁决（仍逐条独立，保持单数语义）。"""
    return [adjudicate(r) for r in reqs]


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        sample = json.loads(sys.argv[1])
    else:
        sample = {
            "target_ip": "192.168.1.1", "port": 80, "method": "POST",
            "path": "/config", "body_preview": "", "is_private_ip": True,
            "request_rate_per_minute": 1,
        }
    print(json.dumps(adjudicate(sample), ensure_ascii=False))
