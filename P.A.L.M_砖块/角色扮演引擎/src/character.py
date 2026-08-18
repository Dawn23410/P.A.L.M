"""角色扮演数据模型：高质量人设卡片。

研究结论（高质量角色扮演必备要素）：
- 性格支柱 + 内在矛盾（3-5 条，矛盾制造张力，避免扁平）
- 声音四维（用词区间 / 句式节奏 / 绝不会说的话 / 口头禅与小动作）
- 示例对话（让模型对齐语气）
- 缺点与脆弱面（角色必须会犯错、会示弱）
- 话痨程度滑块（0-100，控制主动输出量）
- 场景简报（地点 / 时间 / 刚发生的事 / 角色此刻想要什么）
- 目标、价值观、行为准则、安全边界
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage

_LOGGER = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    """声音四维：决定角色「怎么说话」。"""
    vocabulary_range: str = ""      # 用词区间：简白 / 书面 / 诗化 / 俚语…
    sentence_rhythm: str = ""       # 句式节奏：短促利落 / 绵长铺陈 / 碎片化
    never_say: list[str] = field(default_factory=list)   # 绝不会说出口的话
    ticks: list[str] = field(default_factory=list)       # 口头禅 / 标志性小动作


@dataclass
class SceneBrief:
    """场景简报：把角色「放进」一个具体情境。"""
    where: str = ""                 # 场景地点
    when: str = ""                  # 时间
    what_just_happened: str = ""    # 刚刚发生了什么
    what_persona_wants: str = ""    # 角色此刻想要什么


@dataclass
class CharacterCard:
    """一张完整的人设卡片。

    字段对齐社区 Character Card 规范（CCv2/V3）语义：name/personality/scenario/
    first_mes/mes_example/tags/creator_notes。好感度等级与增量不再属于角色卡片——
    由 affinity 砖（affection_rules/official_6stage.yaml）统一管理，所有角色一致；
    角色仅保留 affinity_enabled / affinity_stages 两个开关字段供该砖鸭子读取。
    """
    id: str = ""
    name: str = ""
    tagline: str = ""               # 一句话简介
    personality_pillars: list[str] = field(default_factory=list)   # 3-5 条，含矛盾
    voice: VoiceProfile = field(default_factory=VoiceProfile)
    example_dialogue: list[str] = field(default_factory=list)
    flaws: list[str] = field(default_factory=list)                 # 缺点与脆弱面
    talkativeness: int = 50         # 0-100 话痨程度
    scene: SceneBrief = field(default_factory=SceneBrief)
    background: str = ""            # 背景故事
    goals: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    behavior_rules: list[str] = field(default_factory=list)
    safety_bounds: str = ""         # 安全边界（不可突破现实安全）
    # ── 对齐社区规范（CCv2/V3） ──
    first_mes: str = ""             # 开场白：新会话的第一句（默认 greeting 由官方好感度档位提供）
    alternate_greetings: list[str] = field(default_factory=list)   # 多条可选开场白
    tags: list[str] = field(default_factory=list)                  # 分类/检索标签
    creator_notes: str = ""         # 创作者备注（仅供展示，不注入 prompt）
    format_spec: str = ""
    """对话格式规范，如 "[动作]（神态）<内心独白>\\n每次回复末尾必须输出 {当前好感度：X.XX}" """
    daily_schedule: list[dict] = field(default_factory=list)
    """可选的日常时间表。每项：{"time":"18:00-19:00","activity":"晚餐"}"""
    age_progression: list[dict] = field(default_factory=list)
    """可选的年龄/年级增长路径。每项：{"age":"17","grade":"高二","trigger":"用户说新学期开始了"}"""
    affinity_enabled: bool = True
    """好感度开关：角色是否启用双线好感度。工具型角色可关，关闭时引擎短路、不注入指令、不建存储。"""
    affinity_stages: list[dict] = field(default_factory=list)
    """自定义好感度档位（完全自定义版）。非空则覆盖官方 6 阶。

    每项：{"lower_bound":<float>, "name":<str>, "greeting":<str>, "tone":<str>,
           "max_up":<float>, "max_down":<float>}。范围/梯度/名称/称呼全由用户定。
    为空 → 走官方 6 阶（用户仅可改各阶段 name）。
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "personality_pillars": self.personality_pillars,
            "voice": {
                "vocabulary_range": self.voice.vocabulary_range,
                "sentence_rhythm": self.voice.sentence_rhythm,
                "never_say": self.voice.never_say,
                "ticks": self.voice.ticks,
            },
            "example_dialogue": self.example_dialogue,
            "flaws": self.flaws,
            "talkativeness": self.talkativeness,
            "scene": {
                "where": self.scene.where,
                "when": self.scene.when,
                "what_just_happened": self.scene.what_just_happened,
                "what_persona_wants": self.scene.what_persona_wants,
            },
            "background": self.background,
            "goals": self.goals,
            "values": self.values,
            "behavior_rules": self.behavior_rules,
            "safety_bounds": self.safety_bounds,
            "first_mes": self.first_mes,
            "alternate_greetings": self.alternate_greetings,
            "tags": self.tags,
            "creator_notes": self.creator_notes,
            "format_spec": self.format_spec,
            "daily_schedule": self.daily_schedule,
            "age_progression": self.age_progression,
            "affinity_enabled": self.affinity_enabled,
            "affinity_stages": self.affinity_stages,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterCard":
        voice = raw.get("voice", {}) or {}
        scene = raw.get("scene", {}) or {}
        return cls(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            tagline=raw.get("tagline", ""),
            personality_pillars=raw.get("personality_pillars", []),
            voice=VoiceProfile(
                vocabulary_range=voice.get("vocabulary_range", ""),
                sentence_rhythm=voice.get("sentence_rhythm", ""),
                never_say=voice.get("never_say", []),
                ticks=voice.get("ticks", []),
            ),
            example_dialogue=raw.get("example_dialogue", []),
            flaws=raw.get("flaws", []),
            talkativeness=int(raw.get("talkativeness", 50)),
            scene=SceneBrief(
                where=scene.get("where", ""),
                when=scene.get("when", ""),
                what_just_happened=scene.get("what_just_happened", ""),
                what_persona_wants=scene.get("what_persona_wants", ""),
            ),
            background=raw.get("background", ""),
            goals=raw.get("goals", []),
            values=raw.get("values", []),
            behavior_rules=raw.get("behavior_rules", []),
            safety_bounds=raw.get("safety_bounds", ""),
            first_mes=raw.get("first_mes", ""),
            alternate_greetings=raw.get("alternate_greetings", []),
            tags=raw.get("tags", []),
            creator_notes=raw.get("creator_notes", ""),
            format_spec=raw.get("format_spec", ""),
            daily_schedule=raw.get("daily_schedule", []),
            age_progression=raw.get("age_progression", []),
            affinity_enabled=raw.get("affinity_enabled", True),
            affinity_stages=raw.get("affinity_stages", []),
        )


def _character_dir() -> Path:
    """角色卡片落盘目录：<项目根>/Data/characters。"""
    return Path(fallback_dir(settings.STORAGE_POOL_DIR, __file__)) / "characters"


def builtin_characters() -> list[CharacterCard]:
    """内置角色：除从 Skill 导入的梦瑶外，无额外内置角色。"""
    return []


_MENGYAO_SKILL_PATH: str | None = None


def set_mengyao_skill_path(path: str) -> None:
    """设置梦瑶 Skill 文件路径，供 ensure_builtins 调用。"""
    global _MENGYAO_SKILL_PATH
    _MENGYAO_SKILL_PATH = path


def ensure_builtins(base_dir: Path | None = None) -> None:
    """将内置角色写入磁盘（已存在则跳过），含梦瑶（从 Skill 文件导入）。"""
    base_dir = base_dir or _character_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    for card in builtin_characters():
        path = base_dir / f"{card.id}.json"
        if not path.exists():
            path.write_text(json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # 梦瑶：从 Skill 文件导入（如果文件路径已设置且角色不存在）
    mengyao_path = base_dir / "mengyao.json"
    if not mengyao_path.exists() and _MENGYAO_SKILL_PATH:
        try:
            from .import_skill import import_from_file  # 懒导入避免循环引用
            card = import_from_file(_MENGYAO_SKILL_PATH, "mengyao")
            _LOGGER.info("梦瑶角色已从 Skill 文件导入: %s", card.name)
        except Exception as exc:
            _LOGGER.warning("梦瑶角色导入失败: %s", exc)


def load_character(character_id: str, base_dir: Path | None = None) -> CharacterCard | None:
    """按 id 加载角色卡片；不存在返回 None。"""
    base_dir = base_dir or _character_dir()
    path = base_dir / f"{character_id}.json"
    if not path.exists():
        return None
    try:
        return CharacterCard.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def save_character(card: CharacterCard, base_dir: Path | None = None) -> Path:
    """保存（覆盖）角色卡片，返回落盘路径。"""
    if not card.id:
        raise ValueError("角色卡片缺少 id")
    base_dir = base_dir or _character_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{card.id}.json"
    path.write_text(json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_characters(base_dir: Path | None = None) -> list[dict]:
    """列出全部角色（仅元信息：id / name / tagline）。"""
    base_dir = base_dir or _character_dir()
    ensure_builtins(base_dir)
    result: list[dict] = []
    for path in sorted(base_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        result.append({
            "id": raw.get("id", path.stem),
            "name": raw.get("name", ""),
            "tagline": raw.get("tagline", ""),
        })
    return result