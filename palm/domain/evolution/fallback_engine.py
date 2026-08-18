"""本地兜底引擎：抽取 adjudicator 规则做风险判定，提供本地确定性动作与主动推送模板。

设计要点（源自自主进化架构决策）：
- 不重建决策树——规则来自 adjudicator 砖 capabilities（get_rules / check_action）。
- Eco 模式下主动推送不经过 LLM，改用本地确定性模板（local_proactive_content）。
- should_override 用裁决结果（blocked / deny）替代「LLM 置信度」（当前 llm_bridge 不吐置信度）。
- on_timeout / on_offline 提供保守本地动作，作为 LLM 的三层兜底之一。
"""
from __future__ import annotations

# 本地主动推送模板（eco 模式不经 LLM，按 brief 生成确定性文案）。
_PROACTIVE_TEMPLATES = [
    "我注意到你有一阵子没动静了，要我帮你整理一下今天的待办吗？",
    "顺手提醒：要不要我为你起草当前最紧要的那件事？",
    "你常在这个时段处理这类事务，需要我先帮你备好材料吗？",
]


def local_proactive_content(brief: str) -> str:
    # eco 模式：基于 brief 生成确定性本地推送文案（不调用 LLM）。
    base = (brief or "").strip()
    if base:
        return f"（本地模式）{base}"
    return _PROACTIVE_TEMPLATES[0]


def should_override(adjudication) -> bool:
    # 裁决引擎判定为拒绝/阻塞 → 忽略 LLM 结果，改走本地保守动作。
    if adjudication is None:
        return False
    if getattr(adjudication, "blocked", False):
        return True
    return getattr(adjudication, "action_type", "") == "deny"


def on_timeout() -> str:
    # LLM 超时（>10s）兜底：不执行任何变更，返回保守提示。
    return "（本地兜底）操作超时，已转为保守处理，未执行任何变更。"


def on_offline() -> str:
    # 断网/模型失效兜底：完整降级为离线模式，仅执行本地安全动作。
    return "（本地兜底）网络/模型不可用，已切换离线模式，仅执行本地安全动作。"
