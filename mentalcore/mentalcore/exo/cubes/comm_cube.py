"""通信魔方（微内核之一）：审计日志 + 回传格式化（安全责任三）。

审计后端使用归档 TraceStore（移植自 palm dual/trace_store.py）——Worker 每一步
动作与观测结果作为轨迹写入（工具调用/输出/干预），可摘要、可关键词检索；
Boss 经插槽按需拉取，而非一次性灌入全部上下文。
回传：Worker 完成后把结构化结果格式化为纯文本交给 Boss，
Boss 再用角色卡做语言加工（Worker 自身无性格）。
"""
from ..trace_store import TraceStore, T_OUTPUT, T_TOOL_CALL, T_TOOL_RESULT


class CommCube:
    """通信魔方：全程审计（TraceStore 后端）+ 产出回传文本。"""

    def __init__(self, task_id: str = "exo", task_goal: str = ""):
        self.trace = TraceStore(task_id=task_id, task_goal=task_goal)

    def audit(self, action: str, detail: str, observation: str = "") -> None:
        """写入一条审计轨迹：工具调用记 tool_call(+result)，收尾记 output。"""
        if action == "finish":
            self.trace.add(T_OUTPUT, detail)
        else:
            self.trace.add(
                T_TOOL_CALL, detail,
                metadata={"tool_name": action, "observation": observation})
            if observation:
                self.trace.add(
                    T_TOOL_RESULT, observation,
                    metadata={"tool_name": action, "observation": observation})

    def get_audit(self) -> list[dict]:
        """导出审计（兼容旧结构：action/detail/observation）。"""
        return [
            {"ts": e.timestamp,
             "action": e.metadata.get("tool_name") or e.entry_type,
             "detail": e.content,
             "observation": e.metadata.get("observation", "")}
            for e in self.trace.get_recent(1000)
        ]

    def query(self, keyword: str, top_k: int = 5) -> list[dict]:
        """关键词检索轨迹（对齐 TraceStore.query）。"""
        return [e.to_dict() for e in self.trace.query(keyword, top_k)]

    def get_summary(self) -> str:
        """读取 Worker 轨迹摘要（供 Boss 上下文注入 / 进度查询）。"""
        return self.trace.get_summary()

    def mark_finished(self) -> None:
        """标记 Worker 任务已完成。"""
        self.trace.mark_finished()

    def build_feedback(self, result: str, goal: str) -> str:
        """产出回传 Boss 的纯文本（交由 Boss 做角色卡语言加工）。"""
        steps = "; ".join(
            f"{a['action']}={a['detail']}" for a in self.get_audit()
            if a["action"] not in ("finish", T_TOOL_RESULT))
        return (f"[外骨骼回传] 任务「{goal}」已完成。\n"
                f"执行轨迹：{steps or '无工具调用'}\n"
                f"结论：{result}")
