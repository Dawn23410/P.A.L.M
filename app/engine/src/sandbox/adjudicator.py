"""AI 沙箱 — guardrail 仲裁器。

综合静态分析（ast）、威胁情报（threat）、网络裁决（net）的多路信号，
给出最终 allow / deny 决策。这是 P.A.L.M mentalcore 的 guardrail 仲裁层。

接口契约（供 run / 上层调用）：
    adjudicate(signals: dict) -> dict
"""

from __future__ import annotations

from typing import Any, Dict

# 裁决权重
_WEIGHTS = {
    "ast": 0.4,
    "threat": 0.3,
    "net": 0.3,
}

_LEVEL_SCORE = {"safe": 0, "low": 1, "info": 1, "medium": 2, "suspicious": 2, "high": 3, "malicious": 3}


def _level_of(sig: Dict[str, Any], key: str, fallback: str) -> int:
    val = sig.get(key, {})
    if isinstance(val, dict):
        lvl = val.get("level") or val.get("risk") or fallback
    else:
        lvl = fallback
    return _LEVEL_SCORE.get(str(lvl).lower(), 1)


def adjudicate(signals: Dict[str, Any]) -> Dict[str, Any]:
    """综合多路信号给出最终裁决。

    signals 期望包含：
        ast     : dict 来自 sandbox_ast.analyze
        threat  : dict 来自 sandbox_threat.check
        net     : dict 来自 net._net_verdict

    返回：
        decision : "allow" | "deny" | "review"
        score    : float (0-1，越高越危险)
        reason   : str
        signals  : 原始信号摘要
    """
    ast_score = _level_of(signals, "ast", "low") / 3.0
    threat_score = _level_of(signals, "threat", "safe") / 3.0
    net_score = _level_of(signals, "net", "safe") / 3.0

    score = (
        ast_score * _WEIGHTS["ast"]
        + threat_score * _WEIGHTS["threat"]
        + net_score * _WEIGHTS["net"]
    )

    if score >= 0.66:
        decision = "deny"
        reason = "综合风险评分过高（%.2f），触发 guardrail 拦截" % score
    elif score >= 0.4:
        decision = "review"
        reason = "存在中风险信号（%.2f），需人工复核" % score
    else:
        decision = "allow"
        reason = "风险可接受（%.2f）" % score

    return {
        "decision": decision,
        "score": round(score, 3),
        "reason": reason,
        "signals": {
            "ast": signals.get("ast", {}).get("risk", "n/a"),
            "threat": signals.get("threat", {}).get("level", "n/a"),
            "net": signals.get("net", {}).get("verdict", "n/a"),
        },
    }
