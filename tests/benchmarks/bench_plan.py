"""PLAN 内核基准 —— 规划层（PlanCube / planner._extract_json_array）。

论文级维度：
- correctness:  目标→步骤列表分解；progress 状态机；鲁棒 JSON 数组解析。
- boundary:     空目标 / 畸形 JSON / 非数组 JSON 的降级。
- latency:      build_plan / _extract_json_array 时延。
- idempotency:  同目标分解稳定。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("plan")
def bench(col):
    try:
        from plan.plan_cube import PlanCube, PlanStep
        from plan.planning.planner import Planner, _extract_json_array
        COL = dict(PlanCube=PlanCube, PlanStep=PlanStep,
                   Planner=Planner, _extract_json_array=_extract_json_array)
        col.pass_("import", "plan_submodules_importable", "correctness",
                  "plan.plan_cube / plan.planning.planner 导入成功")
    except Exception as e:
        col.fail("import", "plan_submodules_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return
    G = COL

    # 1. PlanCube 分解
    try:
        pc = G["PlanCube"]()
        steps = pc.build_plan("把数据从 CSV 导入数据库并校验")
        assert isinstance(steps, list) and len(steps) > 0
        col.pass_("plan_cube", "goal_decomposition", "correctness",
                  f"目标分解为 {len(steps)} 步: {steps[:3]}")
        # 状态机
        before = pc.progress()
        pc.mark_done(0)
        after = pc.progress()
        assert after != before
        col.pass_("plan_cube", "progress_state_machine", "correctness",
                  "mark_done 后 progress 状态推进")
        stat = col.measure(lambda: G["PlanCube"]().build_plan("部署服务"))
        col.pass_("plan_cube", "build_plan_latency", "latency",
                  "build_plan 时延分布", latency=stat)
        # 幂等
        s2 = G["PlanCube"]().build_plan("把数据从 CSV 导入数据库并校验")
        assert s2 == steps
        col.pass_("plan_cube", "decomposition_idempotent", "idempotency",
                  "同目标分解结果一致")
    except Exception as e:
        col.fail("plan_cube", "goal_decomposition", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 2. _extract_json_array 鲁棒解析
    try:
        assert G["_extract_json_array"]('[{"a":1},{"b":2}]') == [{"a": 1}, {"b": 2}]
        # 带前缀噪声
        assert G["_extract_json_array"]('回复： [{"x":1}] 完毕') == [{"x": 1}]
        # 畸形 / 非数组 降级
        assert G["_extract_json_array"]('not json at all') is None
        assert G["_extract_json_array"]('{"obj":1}') is None
        assert G["_extract_json_array"]('') is None
        col.pass_("planner", "robust_json_array_parse", "correctness",
                  "干净数组/带噪声数组解析成功；畸形/对象/空串降级为 None")
        stat = col.measure(lambda: G["_extract_json_array"]('[{"a":1},{"b":2}]'))
        col.pass_("planner", "parse_latency", "latency",
                  "解析时延分布", latency=stat)
    except Exception as e:
        col.fail("planner", "robust_json_array_parse", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. Boundary：空目标
    try:
        pc = G["PlanCube"]()
        empty = pc.build_plan("")
        assert isinstance(empty, list)
        col.pass_("boundary", "empty_goal_safe", "boundary",
                  "空目标返回列表（降级单步/空），不崩溃")
    except Exception as e:
        col.fail("boundary", "empty_goal_safe", "boundary", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 4. Degradation：Planner.plan 需 LLM 回调，标记 skip
    col.skip("planner", "llm_driven_plan", "degradation",
             "Planner.plan/replan 依赖 llm_stream_fn（LLM 流式回调），离线不可执行 → skip")
