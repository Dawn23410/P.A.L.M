"""自主规划引擎——计划编排（执行 + 监控 + 重规划）（移植自 palm dual_plan.py）。

PlanEngine 不重新实现 ReAct，而是把「计划中的每一步」当作独立子目标执行
（worker.run_step，步内仍是原生 function-calling 循环）；任一步失败即基于已完成
进展调用 Planner.replan 重新规划剩余步骤，直至计划完成或达到重规划上限。

与归档差异：同步执行（worker.run_step 返回 {text,error}），事件流简化为最终结果文本。
"""
from __future__ import annotations

import logging

from .planner import (
    STEP_PENDING, STEP_DONE, STEP_FAILED, STEP_RUNNING, STEP_SKIPPED,
    Plan, PlanStep, Planner,
)
from .trace_store import T_PLAN, T_ERROR, T_OUTPUT, T_INTERVENTION

_LOGGER = logging.getLogger(__name__)


class PlanEngine:
    """把目标拆成计划、分步执行、失败重规划（同步版）。"""

    def __init__(
        self,
        worker,
        planner: Planner | None = None,
        max_steps: int = 8,
        step_max_iter: int = 6,
        max_replans: int = 2,
        max_total_steps: int = 24,
    ) -> None:
        self._w = worker
        self._planner = planner or Planner()
        self._max_steps = max_steps
        self._step_max_iter = step_max_iter
        self._max_replans = max_replans
        self._max_total_steps = max_total_steps

    def run(self, goal: str) -> dict:
        """制定计划 → 分步执行 → 失败重规划，返回 {"result","trace","plan"}。"""
        trace = self._w.comm.trace
        plan = self._build_plan(goal)
        plan.steps = plan.steps[:self._max_steps]
        self._renumber_steps(plan)
        plan.status = "executing"
        trace.add(T_PLAN, "计划(%d步): %s" % (
            len(plan.steps),
            "; ".join(f"{s.id}.{s.description}" for s in plan.steps)[:500]))

        idx, replan_count, total = 0, 0, 0
        while idx < len(plan.steps):
            if total >= self._max_total_steps:
                plan.status = "failed"
                trace.add(T_ERROR, "达到总步数上限，终止计划")
                break
            step = plan.steps[idx]
            if step.status in (STEP_DONE, STEP_SKIPPED):
                idx += 1
                continue
            iv = self._w._check_interrupt()
            if iv == "cancel":
                plan.status = "failed"
                trace.add(T_ERROR, "任务被 Boss 取消")
                break
            if iv == "pause":
                # _check_interrupt 已阻塞至 resume/cancel；若返回 cancel 上一分支已处理
                continue
            if iv == "redirect":
                new_goal = getattr(self._w, "_redirect_instruction", "")
                if new_goal:
                    goal = new_goal
                    trace.add(T_OUTPUT, f"任务重定向: {goal[:200]}")
                    plan = self._build_plan(goal)
                    plan.steps = plan.steps[:self._max_steps]
                    self._renumber_steps(plan)
                    plan.status = "executing"
                    trace.add(T_PLAN, "重定向计划(%d步)" % len(plan.steps))
                    idx, replan_count = 0, 0
                    continue
            step.status = STEP_RUNNING
            outcome = self._w.run_step(step.description, self._step_max_iter)
            total += 1
            if outcome.get("error"):
                self._on_step_failed(plan, goal, step, outcome, replan_count)
                if outcome.get("_replanned"):
                    replan_count += 1
                if plan.status == "failed":
                    break
                idx = min(len(plan.steps), self._find_next_pending(plan, idx))
                if plan.status == "failed":
                    break
                continue
            step.status = STEP_DONE
            step.result = (outcome.get("text") or "(步骤未返回文本结果)")[:200]
            step.full_result = outcome.get("text") or ""
            idx += 1

        summary = self._summarize(plan)
        answers = [
            s.full_result for s in plan.steps
            if s.status == STEP_DONE and s.full_result.strip()
        ]
        detail = ""
        if answers:
            detail = "\n\n".join(
                f"【步骤 {i + 1} 回答】\n{ans}" for i, ans in enumerate(answers))
        return {"result": summary + ("\n\n" + detail if detail else ""),
                "trace": self._w.comm.get_audit(),
                "plan": plan.to_dict()}

    def _build_plan(self, goal: str) -> Plan:
        """生成初始计划；异常时降级为单步（归档双保险）。"""
        try:
            return self._planner.plan(
                goal,
                tools_summary=self._build_tools_summary(),
                memory_context=self._w.memory.build_injection_context(goal),
                llm_fn=self._w._llm_text,
                total=len(self._w.tools.list_tools()),
                known_tools={t.name for t in self._w.tools.list_tools()},
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("规划异常，退化为单步: %s", exc)
            return Plan(goal=goal, steps=[PlanStep(id=1, description=goal)])

    def _on_step_failed(self, plan, goal, step, outcome, replan_count) -> None:
        """单步失败：标记失败、记失败经验，重规划剩余步骤（含防死循环去重）。"""
        step.status = STEP_FAILED
        step.result = (outcome.get("text") or "执行出错")[:200]
        try:
            self._w.memory.add("error", f"步骤失败[{step.description}]: {step.result[:100]}")
        except Exception:  # noqa: BLE001
            pass
        self._w.comm.trace.add(T_ERROR, f"步骤 {step.id} 失败: {step.result[:120]}")
        if replan_count >= self._max_replans:
            plan.status = "failed"
            return
        try:
            new_plan = self._planner.replan(
                goal, plan, step, outcome.get("text") or "执行出错",
                llm_fn=self._w._llm_text,
                known_tools={t.name for t in self._w.tools.list_tools()},
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("重规划异常")
            plan.status = "failed"
            return
        done = [s for s in plan.steps if s.status in (STEP_DONE, STEP_SKIPPED)]
        base = len(done)
        remaining = []
        for ns in new_plan.steps[base:]:
            if ns.description.strip() == step.description.strip():
                ns.status = STEP_SKIPPED
                ns.result = "与失败步骤重复，已跳过（防死循环）"
                continue
            remaining.append(ns)
        if not remaining:
            plan.status = "failed"
            return
        plan.steps = (done + [step] + remaining)[:self._max_steps]
        self._renumber_steps(plan)
        plan.status = "executing"
        outcome["_replanned"] = True

    def _find_next_pending(self, plan, start: int) -> int:
        for i in range(start, len(plan.steps)):
            if plan.steps[i].status == STEP_PENDING:
                return i
        plan.status = "failed"
        return len(plan.steps)

    def _build_tools_summary(self) -> str:
        """按工具名前缀聚合出「工具类别」摘要，供规划器感知能力边界。"""
        cats: dict[str, list] = {}
        for t in self._w.tools.list_tools():
            name = t.name
            prefix = name.split("_")[0] if "_" in name else name
            cats.setdefault(prefix, []).append(name)
        return "\n".join(
            f"  - {cat} 类（{len(names)} 个，如 {', '.join(names[:4])}）"
            for cat, names in cats.items())

    @staticmethod
    def _summarize(plan: Plan) -> str:
        done = sum(1 for s in plan.steps if s.status == STEP_DONE)
        lines = [f"计划完成（{done}/{len(plan.steps)} 步）："]
        for s in plan.steps:
            mark = "✓" if s.status == STEP_DONE else ("✗" if s.status == STEP_FAILED else "—")
            lines.append(f"  {mark} {s.description}")
        return "\n".join(lines)

    @staticmethod
    def _renumber_steps(plan: Plan) -> None:
        for i, s in enumerate(plan.steps):
            s.id = i + 1
