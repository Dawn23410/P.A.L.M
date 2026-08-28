"""计划魔方（微内核之一）：把目标拆成 ReAct 步骤并跟踪进度。

worker 不强行照搬大型 Planner；这里做轻量分解——默认三段式步骤，
并允许从专业记忆召回相似经验来丰富计划。进度仅供通信魔方审计展示。
"""
from dataclasses import dataclass, field


@dataclass
class PlanStep:
    """计划步骤。"""
    text: str
    done: bool = False


class PlanCube:
    """计划魔方：分解目标 + 跟踪执行进度。"""

    def __init__(self):
        self.steps: list[PlanStep] = []

    def build_plan(self, goal: str, memory_hint: str = "") -> list[str]:
        """生成步骤清单（默认三段式；memory_hint 非空时作为首条经验注入）。"""
        plan = []
        if memory_hint:
            plan.append(f"参考既往经验：{memory_hint}")
        plan += ["明确目标与验收标准", "选择工具并执行", "核对结果并汇总结论"]
        self.steps = [PlanStep(text=t) for t in plan]
        return plan

    def mark_done(self, index: int) -> None:
        if 0 <= index < len(self.steps):
            self.steps[index].done = True

    def progress(self) -> str:
        total = len(self.steps) or 1
        done = sum(s.done for s in self.steps)
        lines = [f"进度 {done}/{total}"] + [
            f"  [{'x' if s.done else ' '}] {s.text}" for s in self.steps
        ]
        return "\n".join(lines)
