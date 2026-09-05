"""GUI 意图编排入口：把「推理中枢 → 执行 → 回写」串成一步闭环。

设计目标（呼应"把 LLM 当兜底、越用越准越快"）：
- 调一次 execute_gui_intent(software_id, intent) 即完成完整链路：先过推理中枢、
  命中(memory/inferred)免 LLM 直接执行、未命中(llm_fallback)才让 LLM 规划、执行后回写置信度。
- 不依赖 LLM 自觉多步编排（plan_route→run→report 三段），把闭环固化进代码层，
  保证"接入"后每次 GUI 意图都自动走推理中枢快路径。
- executor_runner 可注入（默认=真实 AutomationExecutor().run），verify_fn 可选，
  llm_planner_fn 可选（未提供时 needs_llm 路径返回上下文待上层规划）。

调用方（agent/Worker）只需：命中则直接执行、未命中才把 note 给 LLM 规划一次。
"""
from __future__ import annotations

from typing import Callable

from .world_model_cache.reasoning_hub import infer_route, confirm_and_save
from .world_model_cache.path_memory import report_execution
from .web_automator import WEB_SOFTWARE_IDS


async def _default_executor_runner(steps: list[dict], software_id: str | None = None) -> tuple[bool, str]:
    """默认执行器：按 software_id 路由——web 类走浏览器 DOM 通道，其余走桌面 UIA。

    software_id 下传以统一桌面坐标/转移层 sid；web 任务不经 UIA（Chromium 对遍历极敏感）。
    """
    if software_id in WEB_SOFTWARE_IDS:
        from .web_automator import WebAutomationExecutor
        ex = WebAutomationExecutor(software_id=software_id or "chrome")
        try:
            return await ex.run(steps)
        finally:
            await ex.close()
    from .executor import AutomationExecutor
    res = await AutomationExecutor().run(steps, software_id=software_id)
    ok = "状态: 完成" in res
    return ok, res


async def execute_gui_intent(
    software_id: str,
    intent: str,
    llm_planner_fn: Callable | None = None,
    executor_runner: Callable | None = None,
    verify_fn: Callable | None = None,
    target_hwnd: int | None = None,
) -> dict:
    """执行一个 GUI 意图，返回结构化闭环结果。

    返回字段：source/trust/needs_llm/confidence/stale/steps/exec_success/
    llm_used/verify_after/report_confidence/linkage/note/target_hwnd。
    target_hwnd：感知首步选出的目标窗口句柄；透传给执行器确保操作正确窗口（⑦点防误操错窗）。
    """
    route = infer_route(software_id, intent)
    needs_llm = route["needs_llm"]
    steps = route.get("steps") or []
    llm_used = False

    if needs_llm and not steps:
        # 真兜底：需 LLM 规划一次
        if llm_planner_fn is None:
            return {**route, "exec_success": None, "llm_used": False,
                    "verify_after": True, "report_confidence": None,
                    "note": "needs_llm 且未提供 llm_planner_fn，返回上下文待上层规划"}
        planned = await llm_planner_fn(software_id, intent, route.get("context", {}))
        if not planned:
            return {**route, "exec_success": None, "llm_used": True,
                    "verify_after": True, "report_confidence": None,
                    "note": "LLM 未产出步骤"}
        steps = planned
        llm_used = True

    # 目标窗口透传：把感知首步选出的 hwnd 注入每个未显式指定 target 的 step，
    # 执行器 _resolve_target 优先用显式 hwnd，确保操作落在正确窗口（⑦点防误操错窗）。
    if target_hwnd:
        for step in steps:
            if isinstance(step, dict) and not step.get("target"):
                step["target"] = target_hwnd

    # 执行（默认真实执行器；验证时注入 mock）。默认 runner 接收 software_id 统一 sid，
    # 外部注入 runner 维持仅收 steps 的契约（向后兼容）。
    runner = executor_runner or _default_executor_runner
    if runner is _default_executor_runner:
        exec_success, exec_detail = await runner(steps, software_id)
    else:
        exec_success, exec_detail = await runner(steps)

    # 回写闭环：本次若由 LLM 规划则先确认落盘；执行成败双向校准置信度
    if llm_used:
        confirm_and_save(software_id, intent, steps, success=exec_success, source="llm")
    report_execution(software_id, intent, success=exec_success)

    # 重新读取（含本次回写）的置信度
    after = infer_route(software_id, intent)
    report_conf = after.get("confidence")

    # 校验（可选）：verify_after 时由注入的 verify_fn 决定；默认不强制，交调用方
    if route.get("verify_after") and verify_fn is not None and exec_success:
        await verify_fn(software_id, steps)

    return {
        "source": route["source"], "trust": route.get("trust"),
        "needs_llm": needs_llm, "confidence": route.get("confidence"),
        "stale": route.get("stale"), "steps": steps,
        "exec_success": exec_success, "exec_detail": exec_detail,
        "llm_used": llm_used, "verify_after": route.get("verify_after", True),
        "report_confidence": report_conf,
        "linkage": (route.get("context") or {}).get("linkage"),
        "target_hwnd": target_hwnd,
        "note": "",
    }
