"""自主规划引擎 —— 计划编排（执行 + 监控 + 重规划）。

PlanEngine 不重新实现 ReAct，而是复用 Agent.run_react 把「计划中的每一步」
当作一个独立子目标执行；任一步失败即基于已完成进展调用 Planner.replan
重新规划剩余步骤，直至计划完成或达到重规划上限。

对外的可观测性通过 AgentEvent 暴露：
- "plan"       完整计划（plan 字段为步骤列表）
- "plan_step"  单步状态变化（plan_step 字段）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Callable

from .planner import (
    STEP_DONE, STEP_FAILED, STEP_RUNNING, STEP_SKIPPED,
    Plan, PlanStep, Planner,
)
from .schemas import AgentEvent
from .model_router import select_model

_LOGGER = logging.getLogger(__name__)


class PlanEngine:
    """把目标拆成计划、分步执行、失败重规划。"""

    def __init__(
        self,
        agent: Any,
        llm_stream_fn: Callable,
        adjudicator_check_fn: Callable | None,
        planner: Planner | None = None,
        max_steps: int = 8,
        step_max_iter: int = 6,
        max_replans: int = 2,
        step_timeout: int = 180,
        max_total_steps: int = 24,
    ) -> None:
        self._agent = agent
        self._llm = llm_stream_fn
        self._adj = adjudicator_check_fn
        self._planner = planner or Planner()
        self._max_steps = max_steps
        self._step_max_iter = step_max_iter
        self._max_replans = max_replans
        self._step_timeout = step_timeout
        self._max_total_steps = max_total_steps
        # 单次 run 的循环状态（每实例仅服务一次 run）
        self._idx = 0
        self._replan_count = 0
        self._total_executed = 0

    async def run(self, goal: str) -> AsyncIterator[AgentEvent]:
        try:
            self._agent._memory.add("user", goal)

            # ── 直接制定计划（取消调研阶段，避免模型无目的地乱试工具） ──
            yield AgentEvent(type="thought", content="📋 正在制定计划…")
            plan = await self._build_plan(goal, research_findings="")
            plan.steps = plan.steps[:self._max_steps]
            self._renumber_steps(plan)
            plan.status = "executing"
            yield self._emit_plan(plan)
            yield AgentEvent(type="thought", content="✅ 自主规划完成，开始分步执行…")

            self._idx = 0
            self._replan_count = 0
            self._total_executed = 0
            tool_call_history: list = []
            while self._idx < len(plan.steps):
                # 硬上限：跨原始计划 + 重规划的总步数，保证任何情况下都能终止
                if self._total_executed >= self._max_total_steps:
                    plan.status = "failed"
                    yield AgentEvent(
                        type="plan_step",
                        plan_step={"id": self._idx + 1, "description": "(终止)", "status": "failed", "result": ""},
                        content="达到总步数上限，终止计划",
                    )
                    break
                async for ev in self._advance(plan, goal, tool_call_history):
                    yield ev
                self._total_executed += 1
                if plan.status == "failed":
                    break

            summary = self._summarize(plan)
            # 汇总各步真实回答，避免规划模式只回计划清单而丢失答案正文
            answers = [
                step.full_result for step in plan.steps
                if step.status == STEP_DONE and step.full_result.strip()
            ]
            detail = ""
            if answers:
                detail = "\n\n".join(
                    f"【步骤 {i + 1} 回答】\n{answer}"
                    for i, answer in enumerate(answers)
                )
            final_content = summary + ("\n\n" + detail if detail else "")
            yield AgentEvent(type="delta", content=final_content)
            self._agent._memory.add("assistant", summary)  # 记忆只存摘要，避免过长
            yield AgentEvent(type="done")
        except Exception as exc:
            # 任何未预期异常都保证流以 done 收尾，避免前端无限等待
            _LOGGER.exception("规划引擎异常")
            yield AgentEvent(type="delta", content=f"⚠️ 规划执行异常：{str(exc)[:200]}")
            yield AgentEvent(type="done")

    async def _build_plan(self, goal: str, research_findings: str = "") -> Plan:
        """生成初始计划，注入调研结果到规划器，异常时降级为单步。"""
        tools_summary = self._build_tools_summary()
        memory_context = self._agent._memory.inject_system_context()
        total = len(self._agent._tools.list_tools())
        known_tools = {t.spec.name for t in self._agent._tools.list_tools()}
        try:
            return await self._planner.plan(
                goal, tools_summary, memory_context, self._llm,
                select_model("trivial", self._agent._model),
                total, known_tools=known_tools, research_findings=research_findings,
            )
        except Exception as exc:
            _LOGGER.warning("规划异常，退化为单步: %s", exc)
            return Plan(goal=goal, steps=[PlanStep(id=1, description=goal)])

    async def _stream_step(
        self, step, tool_call_history, outcome,
    ) -> AsyncIterator[AgentEvent]:
        """执行单步（按 agent 工具模式分支：native=原生 FC 循环 / 其他=ReAct）。
        隔离异常与超时；异常/超时写入 outcome["error"]。"""
        if self._agent._tool_mode == "native":
            async for ev in self._stream_step_native(step, outcome):
                yield ev
            return
        gen = self._agent.run_react(
            step.description, self._llm, self._adj, tool_call_history, outcome,
            emit_delta=False, emit_done=False, emit_error=False,
        )
        queue: asyncio.Queue = asyncio.Queue()

        async def _pump() -> None:
            try:
                async for ev in gen:
                    await queue.put(("ev", ev))
            except Exception as exc:
                await queue.put(("err", exc))
            finally:
                await queue.put(("stop", None))

        task = asyncio.create_task(_pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), self._step_timeout)
                except asyncio.TimeoutError:
                    outcome["error"] = f"步骤执行超时（>{self._step_timeout}s）"
                    break
                if item[0] == "ev":
                    yield item[1]
                elif item[0] == "err":
                    outcome["error"] = f"步骤执行异常：{str(item[1])[:200]}"
                    break
                else:
                    break
        finally:
            if not task.done():
                task.cancel()
            try:
                await gen.aclose()
            except RuntimeError:
                # 异步生成器因异常/超时处于 running 态时 aclose 会抛 RuntimeError，忽略即可
                pass

    async def _stream_step_native(self, step, outcome) -> AsyncIterator[AgentEvent]:
        """原生 function-calling 模式单步执行：把单步目标作为 user 消息写入记忆后跑原生循环。

        原生循环的 prompt 来自持久历史（get_raw_history），必须把单步描述落进记忆，
        模型才看得到这一步要做什么（react 子步靠 _user_message 临时注入，native 无此机制）。
        抑制 delta 事件（与 react 子步 emit_delta=False 对齐），避免与末尾聚合摘要重复下发。
        临时把 _max_iterations 降到 step_max_iter 约束单步步数，finally 还原避免污染后续。
        """
        self._agent._user_message = step.description
        self._agent._prepare_run(step.description)
        prev_max_iter = self._agent._max_iterations
        self._agent._max_iterations = self._step_max_iter
        gen = self._agent._run_native(
            step.description, self._llm, self._adj, outcome, emit_done=False,
        )

        queue: asyncio.Queue = asyncio.Queue()

        async def _pump() -> None:
            try:
                async for ev in gen:
                    await queue.put(("ev", ev))
            except Exception as exc:
                await queue.put(("err", exc))
            finally:
                await queue.put(("stop", None))

        task = asyncio.create_task(_pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), self._step_timeout)
                except asyncio.TimeoutError:
                    outcome["error"] = f"步骤执行超时（>{self._step_timeout}s）"
                    break
                if item[0] == "ev":
                    # 子步期间不流式 delta，避免与末尾聚合摘要重复
                    if item[1].type == "delta":
                        continue
                    yield item[1]
                elif item[0] == "err":
                    outcome["error"] = f"步骤执行异常：{str(item[1])[:200]}"
                    break
                else:
                    break
        finally:
            self._agent._max_iterations = prev_max_iter
            if not task.done():
                task.cancel()
            try:
                await gen.aclose()
            except RuntimeError:
                pass

    async def _advance(self, plan, goal, tool_call_history) -> AsyncIterator[AgentEvent]:
        """执行 plan.steps[self._idx]，失败时触发重规划。"""
        step = plan.steps[self._idx]
        if step.status in (STEP_DONE, STEP_SKIPPED):
            self._idx += 1
            return
        step.status = STEP_RUNNING
        yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                         content=f"▶ 步骤 {step.id}：{step.description}")

        outcome: dict = {}
        async for ev in self._stream_step(step, tool_call_history, outcome):
            yield ev

        if outcome.get("error"):
            async for ev in self._on_step_failed(plan, goal, step, outcome):
                yield ev
            return
        step.status = STEP_DONE
        step.result = (outcome.get("text") or "(步骤未返回文本结果)")[:200]
        step.full_result = outcome.get("text") or ""  # 保留完整回答，避免规划模式丢答案
        yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                         content=f"✓ 步骤 {step.id} 完成")
        self._idx += 1

    async def _on_step_failed(self, plan, goal, step, outcome) -> AsyncIterator[AgentEvent]:
        """单步失败：保留失败步骤可见，记录失败经验，基于已完成进展重规划剩余步骤。"""
        step.status = STEP_FAILED
        step.result = (outcome.get("text") or "执行出错")[:200]
        # 记录失败轨迹作为程序性记忆，供后续重规划避开该路径
        try:
            self._agent._memory.record_failure(
                goal, step.description, outcome.get("text") or "执行出错",
            )
        except Exception as exc:
            _LOGGER.warning("记录失败经验异常: %s", exc)
        yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                         content=f"✗ 步骤 {step.id} 失败")
        if self._replan_count >= self._max_replans:
            yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                             content="达到重规划上限，终止计划")
            plan.status = "failed"
            self._idx = len(plan.steps)
            return
        self._replan_count += 1
        known_tools = {t.spec.name for t in self._agent._tools.list_tools()}
        try:
            new_plan = await self._planner.replan(
                goal, plan, step, step.result, self._llm,
                select_model("trivial", self._agent._model),
                known_tools=known_tools,
            )
        except Exception as exc:
            _LOGGER.exception("重规划异常")
            plan.status = "failed"
            self._idx = len(plan.steps)
            yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                             content="重规划失败，终止计划")
            return
        done = [s for s in plan.steps if s.status in (STEP_DONE, STEP_SKIPPED)]
        base = len(done)
        new_remaining = new_plan.steps[base:]

        # 防死循环：若重规划生成的步骤描述与失败步骤一致，直接跳过，避免重试同一条已失败路径
        deduped: list = []
        for ns in new_remaining:
            if ns.description.strip() == step.description.strip():
                ns.status = STEP_SKIPPED
                ns.result = "与失败步骤重复，已跳过（防死循环）"
                yield AgentEvent(type="plan_step", plan_step=ns.to_dict(),
                                 content=f"⊘ 步骤 {ns.id} 跳过：与失败步骤重复")
                continue
            deduped.append(ns)
        new_remaining = deduped

        if not new_remaining:
            plan.status = "failed"
            self._idx = len(plan.steps)
            yield AgentEvent(type="plan_step", plan_step=step.to_dict(),
                             content="重规划无有效步骤，终止计划")
            return
        plan.steps = (done + [step] + new_remaining)[:self._max_steps]
        self._renumber_steps(plan)
        plan.status = "executing"
        self._idx = min(base + 1, len(plan.steps))
        if self._idx >= len(plan.steps):
            plan.status = "failed"
            return
        yield self._emit_plan(plan)

    def _build_tools_summary(self) -> str:
        """按工具名前缀聚合出「工具类别」摘要，供规划器感知能力边界。"""
        cats: dict[str, list[str]] = {}
        for t in self._agent._tools.list_tools():
            name = t.spec.name
            prefix = name.split("_")[0] if "_" in name else name
            cats.setdefault(prefix, []).append(name)
        lines = [
            f"  - {cat} 类（{len(names)} 个，如 {', '.join(names[:4])}）"
            for cat, names in cats.items()
        ]
        return "\n".join(lines)

    def _emit_plan(self, plan: Plan) -> AgentEvent:
        return AgentEvent(
            type="plan",
            plan=[s.to_dict() for s in plan.steps],
            content=f"已制定计划（{len(plan.steps)} 步）",
        )

    def _summarize(self, plan: Plan) -> str:
        done = sum(1 for s in plan.steps if s.status == STEP_DONE)
        lines = [f"✅ 计划完成（{done}/{len(plan.steps)} 步）："]
        for s in plan.steps:
            if s.status == STEP_DONE:
                mark = "✓"
            elif s.status == STEP_FAILED:
                mark = "✗"
            else:
                mark = "—"
            lines.append(f"  {mark} {s.description}")
        return "\n".join(lines)

    def _renumber_steps(self, plan: Plan) -> None:
        """步骤 id 重排为 1..N，保证唯一且单调，便于前端按 id 更新。"""
        for i, s in enumerate(plan.steps):
            s.id = i + 1
