"""Mock 模型（demo 用，非真实 LLM）。

体现模型层双通道（设计 §6.1 / §7.2）：
- complete：非流旁路分析（情绪识别等输入侧调用）。
- stream：流式对话主生成（面向用户渲染流式）。
真实接入时替换为 ModelPort 实现；本类仅用于跑通架构与演示。
"""
import random


class MockLLM:
    """极简 Mock：依据角色卡风格生成带人格标签的回复，并附数据区演示拆分。"""

    def __init__(self, persona_name: str = "助手", tone: str = "温和",
                 model_id: str = "mock-pro", context_length: int = 8192,
                 supports_multimodal: bool = False, supports_file: bool = False):
        self.persona_name = persona_name
        self.tone = tone
        self.model_id = model_id
        self.context_length = context_length
        self.supports_multimodal = supports_multimodal
        self.supports_file = supports_file

    def model_info(self) -> dict:
        return {
            "provider": "mock",
            "model_id": self.model_id,
            "context_length": self.context_length,
            "supports_multimodal": self.supports_multimodal,
            "supports_file": self.supports_file,
        }

    def complete(self, prompt: str) -> str:
        """非流旁路分析：demo 用关键词粗略判定情绪三轴向量。"""
        if any(w in prompt for w in ("难过", "伤心", "哭", "委屈")):
            return "valence=-0.4 arousal=0.3 dominance=-0.2"
        if any(w in prompt for w in ("开心", "高兴", "喜欢", "爱")):
            return "valence=0.5 arousal=0.4 dominance=0.1"
        return "valence=0.0 arousal=0.0 dominance=0.0"

    def stream(self, prompt: str):
        """流式生成：yield 正文片段，末尾附数据区供拆分中间件提取。"""
        reply = self._make_reply(prompt)
        for ch in reply:
            yield ch

    def _make_reply(self, prompt: str) -> str:
        """依据 prompt 中的用户输入回声式生成带人格的回复（demo 模板）。

        数据区只演示两类字段：
        - affinity_delta：消费型（拆出，本地结算好感度，不注入 LLM）
        - inner_note：未登记字段 → 外发（演示「其余字段统一打包外发」）
        情绪识别走输入侧 complete 通道，不在此处重复。
        """
        user_text = self._extract_user(prompt)
        tone_hint = f"（{self.tone}）" if self.tone else ""
        body = (f"{tone_hint}我是{self.persona_name}。"
                f"你刚才说「{user_text}」——我记下了，也想说说我的感受。")
        delta = random.choice([0, 1, 1, 2, -1])
        inner_note = random.choice(["（心里偷着乐）", "（有点在意你）", "（默默记下了）"])
        data = f"||DATA||{{\"affinity_delta\":{delta},\"inner_note\":\"{inner_note}\"}}||END||"
        return body + data

    @staticmethod
    def _extract_user(prompt: str) -> str:
        marker = "用户说："
        if marker in prompt:
            return prompt.split(marker)[-1].strip().split("\n")[0]
        return "你好"
