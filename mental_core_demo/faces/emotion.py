"""情感面：好感度引擎 + 情绪识别（设计 §6.4）。

- 整面停用：人格卡 affinity_enabled=False 时整个面禁用（不注入、不结算）。
- 档位内容注入、数值不注入：只给档名/称呼/语气，AI 不自想关系。
- 本地结算器：LLM 只给 delta，base/dynamics/bond 本地计算。
- 情绪识别：共用模型（complete 旁路通道），失败不注入。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule
from ..persona_card import AffinityStage

# 官方六阶档位（情感面向人格取，空则用之）
OFFICIAL_6 = [
    AffinityStage("抵触", "喂", "疏离戒备", -30),
    AffinityStage("陌生", "你", "客气平淡", 0),
    AffinityStage("初识", "朋友", "温和试探", 20),
    AffinityStage("友好", "好友", "亲切自然", 50),
    AffinityStage("亲近", "亲爱的", "亲密熟稔", 80),
    AffinityStage("亲密", "宝贝", "全然信赖", 100),
]


class EmotionFace(BaseFace):
    name = "emotion"

    def __init__(self):
        self.base = 0          # 信任地基 -50~100，慢变
        self.dynamics = 0      # 当下心情 -50~50，快变
        self.bond = 0          # 羁绊，无上限

    def enabled(self, ctx: FaceContext) -> bool:
        return ctx.persona.affinity_enabled

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        if not self.enabled(ctx):
            # 整面禁用：不注入、不结算
            return InjectionModule(source=self.name, content="", available=False)
        stage = self._stage_name(ctx)
        content = (f"【关系】你与用户的关系档位：{stage}。"
                   f"请以该关系下的自然态度回应，不要提及任何数值。")
        return InjectionModule(
            source=self.name, content=content,
            fixed=False, priority=30,
        )

    def _stage_name(self, ctx: FaceContext) -> str:
        stages = ctx.persona.affinity_stages or OFFICIAL_6
        for stage in reversed(stages):
            if self.base <= stage.upper:
                return stage.name
        return stages[-1].name if stages else "陌生"

    def detect_emotion(self, text: str, llm) -> str:
        """共用模型识别用户情绪（输入侧旁路调用）。"""
        return llm.complete(text)

    def settle(self, delta):
        """本地结算好感度（消费型字段）。"""
        if delta is None:
            return
        self.base = max(-50, min(100, self.base + int(delta)))
        # bond 承接 base 溢出（demo 简化）
        if self.base >= 100:
            self.bond += self.base - 100
            self.base = 100
