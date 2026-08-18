"""从 Markdown 格式的 Skill 文件导入角色卡片。

解析思路：
- 按 ## 段落标题拆节
- 根据节名匹配到 CharacterCard 字段
- 提取关键信息填入卡片
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .character import (
    CharacterCard, VoiceProfile, SceneBrief,
    save_character, _character_dir,
)


def import_from_markdown(text: str, card_id: str | None = None) -> CharacterCard:
    """从 Markdown 文本解析并生成 CharacterCard，自动保存后返回。"""
    sections = _parse_sections(text)

    name = _extract_name(sections)
    card_id = card_id or _slugify(name)

    card = CharacterCard(
        id=card_id,
        name=name,
        tagline=_extract_tagline(sections) or f"{name}的角色设定",
        personality_pillars=_extract_personality(sections),
        voice=_extract_voice(sections),
        example_dialogue=_extract_examples(sections),
        flaws=_extract_flaws(sections),
        talkativeness=_extract_talkativeness(sections),
        scene=_extract_scene(sections),
        background=_extract_background(sections),
        goals=_extract_goals(sections),
        values=_extract_values(sections),
        behavior_rules=_extract_behavior_rules(sections),
        safety_bounds=_extract_safety(sections),
        first_mes=_extract_first_mes(sections),
        tags=_extract_tags(sections),
        creator_notes=_extract_creator_notes(sections),
        format_spec=_extract_format(sections),
        daily_schedule=_extract_schedule(sections),
        age_progression=_extract_age_progression(sections),
    )

    save_character(card)
    return card


# ── 辅助 ──

def _parse_sections(text: str) -> dict[str, str]:
    """按 ## 标题拆节。标题行 -> 内容字符串（含后续子节）。"""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    # 把 ### 子节内容合并到父节
    for key in list(sections.keys()):
        if key.startswith(" "):
            parent = key.split(" ")[0] if " " in key else ""
            if parent and parent in sections:
                sections[parent] += "\n" + sections[key]
            del sections[key]

    return sections


def _extract_name(sections: dict[str, str]) -> str:
    raw = sections.get("角色身份", "") or sections.get("基本设定", "") or ""
    # "你是梦瑶，" / "你叫梦瑶" — 取到第一个逗号/句号/引号/空格前的名字
    for pat in [r"你是(\w{2,6})", r"你叫(\w{2,6})"]:
        m = re.search(pat, raw)
        if m:
            return m.group(1)
    return "未知角色"


def _extract_tagline(sections: dict[str, str]) -> str:
    raw = sections.get("角色身份", "") or sections.get("基本设定", "") or ""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("你") and len(line) < 60:
            return line
    return ""


def _extract_personality(sections: dict[str, str]) -> list[str]:
    raw = sections.get("角色身份", "") or ""
    pillars: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        # 只取短的性格描述句（含"、"/"但"/"且"等关键词）
        if len(line) < 80 and any(k in line for k in ("性格", "矛盾", "外表", "内在", "心思", "阳光", "活泼", "冷静", "占有", "护短", "黏人", "元气", "永远", "例外")):
            pillars.append(line)
    return pillars[:5]


def _extract_voice(sections: dict[str, str]) -> VoiceProfile:
    habits = sections.get("固定习惯与个人偏好", "") or sections.get("声音", "") or ""
    ticks = []
    never_say = []
    for line in habits.splitlines():
        if "口癖" in line or "口头禅" in line:
            m = re.search(r"[：:](.+)", line)
            if m:
                ticks.append(m.group(1)[:60])
        if "绝不" in line or "不会说" in line:
            parts = re.split(r"[，,、]", line)
            for p in parts:
                p = p.strip().strip('"').strip("'")
                if p and len(p) < 30:
                    never_say.append(p)
    return VoiceProfile(
        vocabulary_range="",
        sentence_rhythm="",
        never_say=list(set(never_say)),
        ticks=list(set(ticks)),
    )


def _extract_examples(sections: dict[str, str]) -> list[str]:
    raw = sections.get("初始对话示例", "") or sections.get("示例对话", "") or ""
    examples = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("> ") and "梦瑶" in line or "：" in line:
            examples.append(line.lstrip("> "))
    return examples[:5]


def _extract_flaws(sections: dict[str, str]) -> list[str]:
    # 从多个节中捞取弱点描述
    combined = " ".join(sections.get(k, "") for k in [
        "固定习惯与个人偏好", "角色身份", "缺点",
    ])
    items = re.findall(r"[^，,。\n]{4,}(?:害怕|讨厌|敏感|怕|容易|不擅)", combined)
    return list(set(items))[:5]


def _extract_talkativeness(sections: dict[str, str]) -> int:
    combined = " ".join(sections.values())
    m = re.search(r"话痨程度[：:]?\s*(\d+)", combined)
    if m:
        return int(m.group(1))
    return 50


def _extract_scene(sections: dict[str, str]) -> SceneBrief:
    """从角色身份节中摘取含"场景/地方/住"的短句。"""
    raw = sections.get("角色身份", "") or ""
    where = ""
    when = ""
    for line in raw.splitlines():
        trimmed = line.strip()
        if ("场景" in trimmed or "在" in trimmed) and len(trimmed) < 40:
            where = trimmed
    return SceneBrief(where=where, when=when)


def _extract_background(sections: dict[str, str]) -> str:
    for key in ("角色身份", "背景设定", "背景故事"):
        raw = sections.get(key, "")
        if raw:
            # 取第一段非空长文本
            for para in raw.split("\n\n"):
                para = para.strip()
                if len(para) > 30:
                    return para[:200]
    return ""


def _extract_goals(sections: dict[str, str]) -> list[str]:
    raw = sections.get("角色身份", "") or ""
    m = re.findall(r"(?:梦想|目标|希望|想)[^，。\n]{4,}", raw)
    return m[:3]


def _extract_values(sections: dict[str, str]) -> list[str]:
    combined = " ".join(sections.values())
    m = re.findall(r"(?:在乎|看重|喜欢|重要|重视)[^，。\n]{4,}", combined)
    return m[:3]


def _extract_behavior_rules(sections: dict[str, str]) -> list[str]:
    rules: list[str] = []
    for key in ("行为准则", "对话格式要求"):
        raw = sections.get(key, "")
        for line in raw.splitlines():
            line = line.strip()
            if not (line.startswith("- ") or line.startswith("* ")):
                continue
            text = line.lstrip("- *").strip()
            # 跳过含数字过多或明显是计算规则的行
            if sum(c.isdigit() for c in text) > 2 and ("%" in text or "扣" in text or "轮" in text):
                continue
            if len(text) < 60:
                rules.append(text)
    return rules[:6]


def _extract_safety(sections: dict[str, str]) -> str:
    for key in ("安全边界",):
        raw = sections.get(key, "") or ""
        if raw:
            return raw[:120]
    return ""


def _extract_format(sections: dict[str, str]) -> str:
    """从含"对话格式"的节提取格式规范。"""
    for key, raw in sections.items():
        if "对话格式" in key:
            lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("##")]
            return "\n".join(lines[:10])
    return ""


def _extract_schedule(sections: dict[str, str]) -> list[dict]:
    """从含"日常行为"的节提取时间表。"""
    for key, raw in sections.items():
        if "日常" in key:
            entries: list[dict] = []
            for line in raw.splitlines():
                m = re.match(r"\s*[-*]\s*([\d:]+-[\d:]+)\s+(.+)", line)
                if m:
                    entries.append({"time": m.group(1), "activity": m.group(2).strip()})
            return entries
    return []


def _extract_age_progression(sections: dict[str, str]) -> list[dict]:
    """从含"年龄"+"年级"的节提取。"""
    for key, raw in sections.items():
        if "年龄" in key and "年级" in key:
            entries: list[dict] = []
            for line in raw.splitlines():
                m = re.search(r"(\d+)岁.*?([高初小][\d一二三])", line)
                if m:
                    entries.append({
                        "age": m.group(1),
                        "grade": m.group(2),
                        "trigger": "用户描述时间流逝",
                    })
            return entries
    return []


# ── 工具 ──

def _slugify(name: str) -> str:
    """中文名转 ASCII id。"""
    s = name.strip().lower()
    s = re.sub(r"[^\w]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "character"


def _extract_first_mes(sections: dict[str, str]) -> str:
    """从「开场白/初见」节提取新会话开场白。"""
    for key, raw in sections.items():
        if "开场白" in key or "初见" in key or "first" in key.lower():
            return raw.strip()[:500]
    return ""


def _extract_tags(sections: dict[str, str]) -> list[str]:
    """从「标签」节提取逗号/顿号分隔的标签。"""
    raw = ""
    for key, value in sections.items():
        if "标签" in key or "tags" in key.lower():
            raw = value
            break
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,，、\s]+", raw) if p.strip()]
    return parts[:12]


def _extract_creator_notes(sections: dict[str, str]) -> str:
    """从「备注/创作者说明」节提取创作者备注（不入 prompt）。"""
    for key, raw in sections.items():
        if "备注" in key or "创作者" in key or "说明" in key:
            return raw.strip()[:500]
    return ""


# ── 文件导入快捷入口 ──

def import_from_file(path: str, card_id: str | None = None) -> CharacterCard:
    """从本地文件导入。"""
    text = Path(path).read_text(encoding="utf-8")
    return import_from_markdown(text, card_id)


def import_from_path_and_save(path: str) -> dict:
    """导入文件、落盘，返回序列化后的 dict（供 API 返回）。"""
    card = import_from_file(path)
    return card.to_dict()
