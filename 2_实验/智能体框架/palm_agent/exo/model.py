"""外骨骼模型层（模型解耦）：Worker 干活的模型独立于 Boss。

- ExoLLM：生产用，复用心智魔方 PalmLLM 的真实流式收集（MENTALCORE_EXO_MODEL）。
  支持原生工具调用：把工具 schema 交给模型，返回 {text, tool_calls}。
- ExoMockLLM：离线模拟——首轮产出原生 tool_calls、次轮 ||FIN||，供无网自检。
统一暴露 complete(prompt, tools=None) -> {"text","tool_calls"}（Worker ReAct 用）。
"""
import asyncio
import json
import threading
import time
from dataclasses import dataclass

from palm.adapters.model.provider import stream_chat


@dataclass
class _Msg:
    """轻量消息结构（鸭子兼容主工程 _to_oai_messages 的字段访问）。"""

    role: str
    content: str = ""
    tool_calls: list | None = None
    reasoning: str = ""
    tool_call_id: str = ""
    images: list | None = None


def _run_sync(coro):
    """在独立线程的临时事件循环里跑协程（Worker 常在线程中调用，避免 loop 冲突）。"""
    box: dict = {}

    def _target():
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]

# 端点抖动重试：Worker 内部 LLM 调用也需容错（对齐 Boss 侧 PalmLLM 行为）
_MAX_RETRIES = 3
_RETRY_WAIT = (1.0, 2.0, 4.0)


class ExoLLM:
    """干活模型：直接走主工程模型层（原生工具调用 + 独立模型配置）。"""

    def __init__(self, provider_ref, model: str,
                 temperature=None, max_tokens=None):
        self.provider_ref = provider_ref
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def model_info(self) -> dict:
        return {
            "provider": getattr(self.provider_ref, "mode", "openai"),
            "model_id": self.model,
            "base_url": getattr(self.provider_ref, "base_url", ""),
            "reasoning": False,
            "tool_calls": True,
        }

    def _call_once(self, messages, tools) -> dict:
        async def _collect():
            parts: list[str] = []
            calls: list = []
            async for delta in stream_chat(
                messages, model=self.model, provider=self.provider_ref,
                temperature=self.temperature, max_tokens=self.max_tokens,
                tools=tools or None,
            ):
                if delta.content:
                    parts.append(delta.content)
                if delta.tool_calls:
                    calls = delta.tool_calls
            return {"text": "".join(parts), "tool_calls": calls}

        return _run_sync(_collect())

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
