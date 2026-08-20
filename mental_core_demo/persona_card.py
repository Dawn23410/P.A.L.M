"""角色卡数据结构（设计 §6.3）。

静态人格设定；运行时动态由律动面/情感面叠加。
字段：必填 + 对 LLM 可见(静态) + 动态数据变更 + 好感度 + 格式/开场 + 元数据。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AffinityStage:
    """好感度档位（向情感面提供，动态获取，不写死）。"""

    name: str          # 档名，如「友好」
    address: str       # 对用户的称呼
    tone: str          # 语气描述
    upper: int         # 进入该档的 base 上限


@dataclass
class CharacterCard:
    # 必填
    id: str
    name: str
    tagline: str
    personality_pillars: list   # 单条<=6字，最多6条
    flaws: list                 # 同性格限制
    # 对 LLM 可见（静态）
    tone: str = ""
    example_dialogue: str = ""
    background: str = ""
    talkativeness: str = "适中"  # 话少 / 适中 / 话痨
    schedule: list = field(default_factory=list)   # [(时段, 内容)...]
    age: Optional[int] = None
    birthday: Optional[str] = None  # "MM-DD"
    # 动态数据变更
    dynamic_updates_enabled: bool = False
    # 好感度
    affinity_enabled: bool = True
    affinity_stages: list = field(default_factory=list)  # 空=官方6阶
    # 格式与开场
    format_spec: str = "[动作](神态)<内心>正文"
    first_mes: str = ""
    alternate_greetings: list = field(default_factory=list)
    # 元数据（不注入）
    tags: list = field(default_factory=list)
    creator_notes: str = ""


# 官方 6 阶档位（情感面默认，人格卡可覆盖）
OFFICIAL_6 = [
    AffinityStage("抵触", "你", "疏离戒备", -20),
    AffinityStage("陌生", "你", "礼貌客气", 0),
    AffinityStage("初识", "你", "略带亲近", 20),
    AffinityStage("友好", "朋友", "自然熟络", 50),
    AffinityStage("亲近", "挚友", "亲昵松弛", 80),
    AffinityStage("亲密", "宝贝", "独占温柔", 100),
]
