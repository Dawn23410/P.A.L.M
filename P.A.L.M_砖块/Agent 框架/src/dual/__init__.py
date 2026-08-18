"""双模认知引擎（Reflex-Cortex 架构）。

主 Agent（Boss / Reflex）负责快速对话与意图路由；
专业 Agent（Worker / Cortex）负责深度任务执行，轨迹全量记录供主 Agent 检索。

本包是 agent 砖块的平行副本，不修改原始源码：
- dual_core.py      ← core.py
- dual_prompt.py    ← agent_prompt_mixin.py
- dual_runner.py    ← native_runner.py
- dual_plan.py      ← plan_engine.py
- dual_planner.py   ← planner.py
- trace_store.py    新增：Worker 轨迹存储
- intent_router.py  新增：意图路由
- coordinator.py    新增：双 Agent 协调器
"""
