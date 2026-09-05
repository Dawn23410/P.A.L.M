"""自主规划引擎 —— 计划生成与重规划。

把用户目标拆解为有序、可执行的步骤（Plan），并在某步失败时基于已有进展
重新规划（replan）。规划本身依赖 LLM，但解析与降级完全本地、零外部依赖。

设计要点：
- Planner 只负责「产出结构化计划」与「重规划」，不执行任何工具。
- 解析失败或返回空计划时，降级为单步计划（即把目标当作唯一一步），
  保证规划引擎在 LLM 异常时等效退化为普通 ReAct 执行。
- LLM 调用复用 Agent 已有的流式桥接（llm_stream_fn(messages, model) -> AsyncIterator[dict]，
  dict 含 content/reasoning 两种增量，规划只取 content 拼成文本）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

_LOGGER = logging.getLogger(__name__)

# 步骤状态机
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"


@dataclass
class PlanStep:
    """计划中的单个步骤。"""

    id: int
    description: str
    tool: str = ""
    status: str = STEP_PENDING
    result: str = ""
    full_result: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "status": self.status,
            "result": self.result,
            "full_result": self.full_result,
        }


@dataclass
class Plan:
    """一次完整规划。"""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "draft"  # draft | executing | done | failed

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }


_PLANNER_SYSTEM = """你是一个严谨的任务规划器，遵循「先调研、再确认、后执行」的三段式流程。\
给定一个目标与可用工具类别，把目标拆解成有序、可执行的步骤。每一步应能在 1~3 次工具调用内完成。

核心原则——禁止凭空假设：
1. 前 1~2 步必须是信息调研步骤（搜索文件、读取内容、查询数据等），\
   确认事实后再安排执行性步骤。调研步骤必须具体——明确搜索什么、读什么文件。
2. 执行性步骤（写文件、改代码、调 API、部署等）只能在调研确认了必要事实后出现。
3. 步骤从用户视角描述「要做什么」，不暴露内部实现。
4. 每步的 tool 字段可选——若明显对应某个工具可填写建议工具名（不确认则留空）。
5. 步骤数量适中（通常 2~6 步），避免无意义的碎步。
6. 只输出一个 JSON 数组，不要任何解释文字。

输出格式示例：
[
  {"description": "搜索与任务相关的现有文件和记录", "tool": "search_file"},
  {"description": "读取搜索结果中的关键文件，确认当前状态", "tool": "read_file"},
  {"description": "根据确认的信息，修改文件 A", "tool": "write_file"}
]"""


_PLANNER_USER = """目标：{goal}

可用工具类别（共 {total} 个工具）：
{tools_summary}

对话背景摘要：
{memory_context}

{research_block}请输出完成该目标的步骤 JSON 数组。"""


_REPLANNER_SYSTEM = """你是任务规划器。当前计划某步执行失败，请基于「已完成步骤」\
与「失败原因」修订并输出「剩余步骤」的 JSON 数组（不含已完成步骤）。

要求：
1. 不要重复已完成步骤。
2. 严禁重复失败步骤——失败说明这条路径行不通，必须换工具 / 换方法 / 换角度。
   例如：原步骤是「搜索文件中标识身份的记录」失败，应该改为「读取登录配置/历史对话」或「询问用户身份」，
   而不是再次生成一模一样的搜索步骤。
3. 如果再次尝试无法避免重复失败，直接输出空数组（让计划终止，避免死循环）。
4. 针对失败原因调整策略（换工具 / 拆分更细 / 跳过不可行项）。
5. 只输出剩余步骤的 JSON 数组，不要解释。"""


_REPLANNER_USER = """原目标：{goal}

已完成步骤：
{done_summary}

失败步骤：{failed_description}
失败原因：{error}

请输出修订后的剩余步骤 JSON 数组。"""


class Planner:
    """调用 LLM 生成 / 修订计划。"""

    async def plan(
        self,
        goal: str,
        tools_summary: str,
        memory_context: str,
        llm_fn: Callable,
        model: str,
        total: int = 0,
        known_tools: set[str] | None = None,
        research_findings: str = "",
    ) -> Plan:
        """生成计划；解析失败则降级为单步计划。known_tools 用于校验工具提示。"""
        research_block = ""
        if research_findings.strip():
            research_block = (
                "以下是执行任务前已搜集到的信息（请充分利用，不要再重复调研）：\n"
                f"{research_findings.strip()}\n\n"
            )
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": _PLANNER_USER.format(
                goal=goal, tools_summary=tools_summary or "(无)",
                memory_context=memory_context or "(无)", total=total,
                research_block=research_block,
            )},
        ]
        raw = await self._call_llm(messages, llm_fn, model)
        steps_data = _extract_json_array(raw)
        if not steps_data:
            _LOGGER.warning("规划解析失败，降级为单步计划")
            return Plan(goal=goal, steps=[PlanStep(id=1, description=goal)])
        steps = [
            PlanStep(id=i + 1, description=str(d.get("description", "")).strip(),
                     tool=self._ground_tool(d.get("tool"), known_tools))
            for i, d in enumerate(steps_data)
            if str(d.get("description", "")).strip()
        ]
        if not steps:
            return Plan(goal=goal, steps=[PlanStep(id=1, description=goal)])
        return Plan(goal=goal, steps=steps)

    async def replan(
        self,
        goal: str,
        plan: Plan,
        failed_step: PlanStep,
        error: str,
        llm_fn: Callable,
        model: str,
        known_tools: set[str] | None = None,
    ) -> Plan:
        """基于失败重规划，返回「只含剩余步骤」的新 Plan。"""
        done = [s for s in plan.steps if s.status in (STEP_DONE, STEP_SKIPPED)]
        done_summary = "\n".join(
            f"  - {s.id}. {s.description}（{s.result[:80]}）" for s in done
        ) or "  (无)"
        messages = [
            {"role": "system", "content": _REPLANNER_SYSTEM},
            {"role": "user", "content": _REPLANNER_USER.format(
                goal=goal, done_summary=done_summary,
                failed_description=failed_step.description, error=error[:300],
            )},
        ]
        raw = await self._call_llm(messages, llm_fn, model)
        steps_data = _extract_json_array(raw)
        if not steps_data:
            _LOGGER.warning("重规划解析失败，保留原剩余步骤")
            return plan
        new_steps = [
            PlanStep(id=i + 1, description=str(d.get("description", "")).strip(),
                     tool=self._ground_tool(d.get("tool"), known_tools))
            for i, d in enumerate(steps_data)
            if str(d.get("description", "")).strip()
        ]
        if not new_steps:
            return plan
        # 重编号，并接续已完成步骤的编号
        base = len(done)
        for i, s in enumerate(new_steps):
            s.id = base + i + 1
        merged = done + new_steps
        return Plan(goal=goal, steps=merged)

    async def _call_llm(self, messages: list[dict], llm_fn: Callable, model: str) -> str:
        """复用流式桥接收集完整输出文本（规划只需正文，排除推理链 reasoning）。"""
        collected = ""
        try:
            async for chunk in llm_fn(messages, model):
                # 兼容上游 dict（{content}/{reasoning}）与纯字符串两种格式
                if isinstance(chunk, dict):
                    text = chunk.get("content") or ""
                elif isinstance(chunk, str):
                    text = chunk
                else:
                    text = getattr(chunk, "content", None) or getattr(chunk, "delta", "") or ""
                if text:
                    collected += text
        except Exception as exc:
            _LOGGER.warning("规划 LLM 调用异常: %s", exc)
        return collected

    @staticmethod
    def _ground_tool(tool: Any, known_tools: set[str] | None) -> str:
        """工具提示须对应真实已注册工具，无效提示清空以免误导。"""
        tool = str(tool or "").strip()
        if not tool:
            return ""
        if known_tools is not None and tool not in known_tools:
            return ""
        return tool


def _extract_json_array(text: str) -> list[dict] | None:
    """从 LLM 输出中鲁棒提取 JSON 数组。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [d for d in data if isinstance(d, dict)]
