"""情感面：好感度引擎 + 情绪识别（设计 §6.4）。

- 整面停用：人格卡 affinity_enabled=False 时整个面禁用（不注入、不结算）。
- 档位内容注入、数值不注入：只给档名/称呼/语气，AI 不自想关系。
- 本地结算器：LLM 只给 delta，base/dynamics/bond 本地计算。
- 情绪识别：共用模型（complete 旁路通道），失败不注入。
"""
import re

from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule
from ..persona_card import (AffinityStage, DEFAULT_SAFETY, OFFICIAL_6,
                            SEVERE_DROP)


class EmotionFace(BaseFace):
    name = "emotion"

    def __init__(self, base: float = 0, bond: float = 0, dynamics: float = 0):
        # 初始状态由外部注入（storage.load_affinity 恢复，重启不归零）
        self.base = base          # 信任地基 -50~100，慢变
        self.dynamics = dynamics  # 当下心情 -50~50，快变
        self.bond = bond          # 羁绊，无上限

    def enabled(self, ctx: FaceContext) -> bool:
        return ctx.persona.affinity_enabled

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        if not self.enabled(ctx):
            # 整面禁用：不注入、不结算
            return InjectionModule(source=self.name, content="", available=False)
        stage = self._current_stage(ctx)
        lo, hi = stage.delta_range
        content = (f"【关系】你与用户的关系等级：{stage.name}。{stage.description} "
                   f"语气：{stage.tone}。称呼：{stage.address or '无'}。"
                   f"好感度增减范围：{lo} ~ {hi}（仅内部参考，回复勿提数值）。")
        # 严重降低：隐藏档位，固定 prompt 每轮发送，AI 自由裁定是否触发
        slo, shi = SEVERE_DROP.delta_range
        safety = (ctx.persona.safety or DEFAULT_SAFETY).strip()
        content += (f"\n【严重受损指引（仅内部参考，回复勿提）】"
                    f"若本句使关系严重受损（单次好感度扣分 {shi} ~ {slo}）：{safety}")
        return InjectionModule(
            source=self.name, content=content,
            fixed=False, priority=30,
        )

    def _current_stage(self, ctx: FaceContext):
        stages = ctx.persona.affinity_stages or OFFICIAL_6
        # 正向遍历：取第一个 base<=upper 的档（base=1 落在「初识」，而非反向误判亲密）
        for stage in stages:
            if stage.hidden:
                continue  # 隐藏档位不参与正常档位遍历
            if self.base <= stage.upper:
                return stage
        return stages[-1] if stages else None

    def _stage_name(self, ctx: FaceContext) -> str:
        stage = self._current_stage(ctx)
        return stage.name if stage else "陌生"

    def detect_emotion(self, text: str, llm) -> str:
        """共用模型识别用户情绪（输入侧旁路调用）。"""
        return llm.complete(text)

    def settle(self, delta, emotion=None):
        """本地结算好感度（小数制，消费型字段）。

        - base（信任地基）：按模型给出的 delta（可为小数，如 +0.2/-0.4）结算，
          溢出部分转入 bond。全正每轮 +0.1~+0.2 → 约 500~1000 轮到亲密（100）。
        - dynamics（当下心情）：随用户情绪 valence 滑动，快变；让情感面真正"活"。
        """
        if delta is not None:
            raw = self.base + float(delta)
            if raw > 100:
                # bond 承接 base 溢出（亲密档溢出累积）——先算溢出再截断，否则恒为 0
                self.bond = round(self.bond + raw - 100, 2)
                self.base = 100
            else:
                self.base = max(-50, round(raw, 2))  # 2 位小数精度，消浮点尾巴
        if emotion is not None:
            valence = self._parse_valence(emotion)
            # 当下心情快变：valence 正向抬升、负向压低，幅度较 base 更灵敏
            self.dynamics = max(-50, min(50, self.dynamics + round(valence * 4)))

    @staticmethod
    def _parse_valence(emotion_str: str) -> float:
        if not emotion_str:
            return 0.0
        m = re.search(r"valence\s*=\s*(-?\d+(?:\.\d+)?)", emotion_str)
        return float(m.group(1)) if m else 0.0
