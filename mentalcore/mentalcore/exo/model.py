"""外骨骼模型层（模型解耦）：Worker 干活的模型独立于 Boss。

- ExoLLM：生产用，复用心智魔方 PalmLLM 的真实流式收集（MENTALCORE_EXO_MODEL）。
  支持原生工具调用：把工具 schema 交给模型，返回 {text, tool_calls}。
- ExoMockLLM：离线模拟——首轮产出原生 tool_calls、次轮 ||FIN||，供无网自检。
统一暴露 complete(prompt, tools=None) -> {"text","tool_calls"}（Worker ReAct 用）。
"""
import json
import time

from ..llm import _Msg, PalmLLM

# 端点抖动重试：Worker 内部 LLM 调用也需容错（对齐 Boss 侧 PalmLLM 行为）
_MAX_RETRIES = 3
_RETRY_WAIT = (1.0, 2.0, 4.0)


class ExoLLM:
    """干活模型：桥接 PalmLLM（原生工具调用 + 独立模型配置）。"""

    def __init__(self, provider_ref, model: str,
                 temperature=None, max_tokens=None):
        self._inner = PalmLLM(provider_ref, model, temperature, max_tokens)
        self.model = model

    def model_info(self) -> dict:
        return self._inner.model_info()

    def _call_once(self, messages, tools) -> dict:
        if tools:
            return self._inner.collect_with_tools(
                messages, tools, max_tokens=self._inner.max_tokens,
                temperature=self._inner.temperature)
        text = self._inner._collect(
            messages, max_tokens=self._inner.max_tokens,
            temperature=self._inner.temperature)
        return {"text": text, "tool_calls": []}

    def complete(self, prompt: str, tools: list | None = None) -> dict:
        """收集式完成：tools 非空走原生 function calling，返回 {"text","tool_calls"}。

        端点断连/超时自动重试（递增等待）；重试耗尽后抛给上层兜底回传失败。
        """
        messages = [_Msg(role="system", content=""),
                    _Msg(role="user", content=prompt)]
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self._call_once(messages, tools)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_WAIT[attempt])
        raise RuntimeError(f"端点多次重试仍失败：{last_exc}") from last_exc


class ExoMockLLM:
    """离线干事模型：确定性模拟 ReAct（原生 tool_calls），触发真实工具/沙箱路径以便自检。"""

    def __init__(self, demo_tool: tuple | None = None):
        self.model = "exo-mock"
        self.demo_tool = demo_tool  # (工具名, 参数) 或 None

    def model_info(self) -> dict:
        return {"provider": "mock", "model_id": "exo-mock",
                "tool_calls": True, "reasoning": False}

    def complete(self, prompt: str, tools: list | None = None) -> dict:
        if "Observation:" in prompt:  # 已执行过工具 → 收尾
            return {"text": ('||FIN||{"result":"已完成委派任务的离线模拟，'
                             '已调用工具并汇总结论。"}||END||'),
                    "tool_calls": []}
        if not self.demo_tool:
            return {"text": ('||FIN||{"result":"当前无可用工具，直接以文本作答。"}||END||'),
                    "tool_calls": []}
        name, args = self.demo_tool
        return {
            "text": "",
            "tool_calls": [{
                "id": "call_exo_mock", "type": "function",
                "function": {"name": name,
                             "arguments": json.dumps(args, ensure_ascii=False)},
            }],
        }
