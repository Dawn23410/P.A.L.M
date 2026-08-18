"""人设渲染器：对 AI 说最直白的话，信息量给足但不塞过程规则。

每行都是直接命令，没有"请""自然""可以"等模糊词。
把 AI 当完全不懂角色扮演的新手——明确告诉它每件事怎么做，
但不暴露引擎负责的计算逻辑。
"""
from __future__ import annotations

from .character import CharacterCard


def _render_intro(card: CharacterCard) -> list[str]:
    """人设开场：身份与角色化回应基调。"""
    return [
        f"你扮演 {card.name}。{card.tagline}",
        "以角色身份回应——语气、称呼、口癖按角色来。当需要操作电脑时，自然地说出你要用的工具和步骤。",
    ]


def _render_personality(card: CharacterCard) -> list[str]:
    if not card.personality_pillars:
        return []
    lines = ["", "性格："]
    for p in card.personality_pillars[:4]:
        lines.append(f"· {p}")
    return lines


def _render_voice(v: "VoiceProfile") -> list[str]:
    has_voice = v.vocabulary_range or v.sentence_rhythm or v.never_say or v.ticks
    if not has_voice:
        return []
    lines = ["", "说话方式："]
    if v.vocabulary_range:
        lines.append(f"· 用词：{v.vocabulary_range}")
    if v.sentence_rhythm:
        lines.append(f"· 句式：{v.sentence_rhythm}")
    if v.never_say:
        lines.append(f"· 禁止说：{'，'.join(v.never_say[:5])}")
    if v.ticks:
        lines.append(f"· 口癖：{'，'.join(v.ticks[:4])}")
    return lines


def _render_dialogue(dialogue: list[str]) -> list[str]:
    if not dialogue:
        return []
    lines = ["", "语气参考（不是叫你照抄）："]
    for ex in dialogue[:3]:
        short = ex.strip()
        if len(short) > 60:
            short = short[:57] + "..."
        lines.append(f"· {short}")
    return lines


def _render_behavior(rules: list[str]) -> list[str]:
    if not rules:
        return []
    lines = ["", "必须遵守的规则："]
    for r in rules[:5]:
        lines.append(f"· {r}")
    return lines


def _render_talkativeness(value: int) -> list[str]:
    return ["", _talkativeness_guidance(value)]


def _render_scene(s) -> list[str]:
    if not (s.where or s.when or s.what_just_happened):
        return []
    lines = ["", "当前场景："]
    if s.where:
        lines.append(f"· 地点：{s.where}")
    if s.when:
        lines.append(f"· 时间：{s.when}")
    if s.what_just_happened:
        lines.append(f"· 刚刚：{s.what_just_happened}")
    return lines


def render_persona(card: CharacterCard) -> str:
    """出干净、直接、信息完整的人设 prompt。"""
    lines: list[str] = []
    lines += _render_intro(card)
    lines += _render_personality(card)
    lines += _render_voice(card.voice)
    lines += _render_dialogue(card.example_dialogue)
    lines += _render_behavior(card.behavior_rules)
    lines += _render_talkativeness(card.talkativeness)
    lines += _render_scene(card.scene)
    if card.format_spec:
        lines.append("")
        lines.extend(card.format_spec.splitlines()[:4])
    if card.safety_bounds:
        lines.append("")
        lines.append(card.safety_bounds[:120])
    return "\n".join(lines)


def _talkativeness_guidance(value: int) -> str:
    if value <= 20:
        return f"话少（{value}）：对方不问就不说。"
    if value <= 45:
        return f"偏安静（{value}）：点到即止，不主动找话。"
    if value <= 70:
        return f"适中（{value}）：正常聊，有问有答。"
    if value <= 90:
        return f"活泼（{value}）：主动分享、接梗。"
    return f"话痨（{value}）：停不下来，但正事能收住。"
