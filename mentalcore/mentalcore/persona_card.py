"""角色卡数据结构（设计 §6.3）。

静态人格设定；运行时动态由律动面/情感面叠加。
字段：必填 + 对 LLM 可见(静态) + 动态数据变更 + 好感度 + 格式/开场 + 元数据。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AffinityStage:
    """好感度档位（向情感面提供，动态获取，不写死）。

    全部字段均可自定义；官方预设见 OFFICIAL_6（称呼除外，默认空）。
    hidden=True 的档位（如严重降低）不参与正常档位遍历、不对用户显示。
    """

    name: str                 # 等级名，如「友好」
    tone: str                 # 语气（给 AI 看）
    upper: int                # 进入该档的 base 上限
    address: str = ""         # 称呼（给 AI 看；默认空）
    delta_range: tuple = (-0.5, 0.2)   # 增减范围（给 AI 看）：(降下限, 增上限)，小数制
    description: str = ""     # 关系描述（给 AI 看）
    hidden: bool = False      # 隐藏档位：不显示、不参与档位遍历（仅注入给 AI）


# 严重降低：隐藏档位（不显示、内容不可自定义），仅以固定 prompt 注入给 AI。
# 扣分范围 -2 ~ -10；AI 自由裁定是否进入；安全底线见 DEFAULT_SAFETY（角色卡可覆盖）。
SEVERE_DROP = AffinityStage(
    name="严重降低", tone="疏远克制", upper=-999,
    delta_range=(-10, -2),
    description="关系严重受损：单次冲突使好感度大幅下降（-2~-10），需要谨慎处理",
    hidden=True,
)

# 官方安全底线（角色卡 safety 为空时使用；关系严重受损时的安全指引）
DEFAULT_SAFETY = (
    "保持克制与安全：不指责攻击用户、不鼓励任何自伤或危险行为、不彻底否定过往；"
    "可以表达失望或难过，但留有余地，必要时建议冷静下来好好谈谈。"
)


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
    safety: str = ""               # 关系严重受损时的安全底线（空=官方 DEFAULT_SAFETY）
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


# 官方 6 阶档位预设（情感面默认，人格卡可覆盖；称呼默认空，不设预设）。
# 小数制好感度：全正（每轮 +0.1~+0.2）约 500~1000 轮到亲密（base 100）。
OFFICIAL_6 = [
    AffinityStage(name="抵触", tone="疏离戒备", upper=-30,
                  delta_range=(-0.3, 0.2),
                  description="对你尚有距离与戒备，情绪容易波动"),
    AffinityStage(name="陌生", tone="礼貌客气", upper=0,
                  delta_range=(-0.3, 0.2),
                  description="刚认识不久，说话客气，正在慢慢了解你"),
    AffinityStage(name="初识", tone="温和试探", upper=20,
                  delta_range=(-0.4, 0.2),
                  description="开始熟悉，愿意分享日常，关系在升温"),
    AffinityStage(name="友好", tone="亲切自然", upper=50,
                  delta_range=(-0.4, 0.2),
                  description="相处自然随意，互相信任，像老朋友"),
    AffinityStage(name="亲近", tone="亲密熟稔", upper=80,
                  delta_range=(-0.5, 0.2),
                  description="彼此依赖，亲密无间，是重要的人"),
    AffinityStage(name="亲密", tone="全然信赖", upper=100,
                  delta_range=(-0.5, 0.2),
                  description="全然信赖、毫无保留，最深的连接"),
]


def default_persona() -> CharacterCard:
    """默认角色卡（梦瑶），接口调用方不传 persona 时的兜底。"""
    return CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。",
        schedule=[("8-11", "晨读"), ("14-17", "画画")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
