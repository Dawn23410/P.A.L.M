"""Mock 提供方：无需真实 API Key，用于本地测试与演示端到端流式链路。

complete() 模拟一个真实模型的行为：
  - 产出若干增量 token（逐片 yield，便于验证 SSE / 打字机渲染）
  - 末尾产出 done 事件（携带 usage）
  - 不调用 _check_key，因此即使 api_key 为空也能工作
支持多模态：若消息携带图片，会在回显中体现。
"""
from __future__ import annotations

import asyncio

from ..models import Message, ModelParameters, ProviderConfig
from .base import BaseProvider


class MockProvider(BaseProvider):
    """本地模拟提供方，回声 + 参数回显，验证对话调度链路。"""

    # 覆盖基类：不要求 API Key
    def _check_key(self) -> None:  # pragma: no cover - 故意不校验
        return

    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        last_user = ""
        has_image = False
        for m in reversed(messages):
            if m.role == "user":
                last_user = m.content
                has_image = bool(m.images)
                break

        img_note = "（检测到多模态图片，已纳入上下文）" if has_image else ""
        reply = (
            f"[Mock 回复] 已收到你的消息：{last_user!r}{img_note}\n"
            f"调用参数 -> 模型={model}, temperature={params.temperature}, "
            f"top_p={params.top_p}, max_tokens={params.max_tokens}。\n"
            "这是一段由 Mock 提供方生成的模拟流式输出，"
            "用于验证『前端/CLI -> 后端调度 -> Provider 流式生成 -> 落盘』整条链路是否打通。"
        )

        # 分片模拟 token 流；非流式模式则一次性返回
        if not stream:
            yield {"content": reply}
            yield {"done": True, "usage": {
                "prompt_tokens": len(last_user),
                "completion_tokens": len(reply),
            }}
            return

        step = 8
        for i in range(0, len(reply), step):
            await asyncio.sleep(0.008)  # 轻微延迟，贴近真实首字/逐字节奏
            yield {"content": reply[i : i + step]}
        yield {"done": True, "usage": {
            "prompt_tokens": len(last_user),
            "completion_tokens": len(reply),
        }}
