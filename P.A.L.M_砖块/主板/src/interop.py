"""跨砖能力取用助手：各砖经此惰性取用其它砖暴露的门面对象。

设计：砖间严格零互导，只经 registry 的 capabilities 通信。这里把「按砖名取
capabilities['xxx_api']」封装为带缓存与缺失降级（返回 None）的助手，避免每处
调用都重复写 registry.get + .capabilities.get。缺失即 None，由各消费方自行降级。

主板架构（2026-08-06）：get_facade(name) 为统一取用入口（北桥能力总线），
原 get_roleplay_api 等具体函数保留为薄包装（兼容既有 31 处调用点，零改动）。
"""
from __future__ import annotations

from palm_sdk.bricks.base import registry
from .arbitration import proxy_facade

# 哨兵：区分「尚未取用过」与「确实缺失（None）」，避免砖后注册时缓存到旧值。
_MISSING = object()
_facade_caches: dict[str, object] = {}

# 砖名 -> capability 键的约定映射（北桥能力总线的地址表）。
_FACADE_CAP = {
    "roleplay": "roleplay_api",
    "affinity": "affinity_api",
    "memory": "memory_api",
    "evolution": "evolution_api",
    "agent": "agent_api",
}


def get_facade(brick_name: str):
    """统一取用门面：按砖名取 capabilities[<brick>_api]，带缓存与缺失降级。

    缺失（砖未注册 / 能力不存在）返回 None，由消费方自行降级（铁律）。
    """
    cache_key = brick_name
    if cache_key not in _facade_caches:
        cap_key = _FACADE_CAP.get(brick_name, f"{brick_name}_api")
        brick = registry.get(brick_name)
        raw = (brick.capabilities.get(cap_key) if brick else None) or None
        # 零信任闭环：裸门面经代理包裹，跨砖调用强制过管理芯片（遥测/健康观测）。
        _facade_caches[cache_key] = proxy_facade(brick_name, raw)
    return _facade_caches[cache_key]


def get_roleplay_api():
    """取角色扮演砖暴露的门面（人设/角色卡/语气守卫全部符号，不含好感度）。"""
    return get_facade("roleplay")


def get_affinity_api():
    """取好感度砖暴露的门面（AffinityState / settle_from_model / AffinityStore 等）。"""
    return get_facade("affinity")


def get_memory_api():
    """取记忆砖暴露的门面（Memory / CoreMemory / purge_vector_by_conv_id 等）。"""
    return get_facade("memory")


def get_evolution_api():
    """取自主进化砖暴露的门面（scheduler / run_proactive / touch_activity 等）。"""
    return get_facade("evolution")


def get_agent_api():
    """取 Agent 砖暴露的门面（run_proactive_stream / push_bubble / memory_path 等）。

    evolution 砖经此回调 agent 的流式推送与气泡能力，避免反向 import agent 内部符号。
    """
    return get_facade("agent")