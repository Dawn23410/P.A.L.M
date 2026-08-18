# 跨砖 API 网关：独立运行态下经注册表惰性解析各砖 capability。
#
# 与项目「砖间严格物理解耦、经 capability 取用」的契约一致——调用方拿到的是
# 目标砖经 capabilities 暴露的函数/对象，而非跨砖硬 import。未注册或未暴露该
# capability 时返回 None，由调用方自行降级（绝不抛「砖未注册」阻断请求）。
from palm_sdk.bricks.base import registry


def _resolve(brick_name: str, cap_key: str):
    """惰性取已注册砖的指定 capability；未注册/未暴露即返回 None。"""
    brick = registry.get(brick_name)
    if brick is None:
        return None
    return (getattr(brick, "capabilities", None) or {}).get(cap_key)


def get_roleplay_api():
    return _resolve("roleplay", "roleplay_api")


def get_evolution_api():
    return _resolve("evolution", "evolution_api")


def get_memory_api():
    return _resolve("memory", "memory_api")


def get_affinity_api():
    return _resolve("affinity", "affinity_api")


def get_agent_api():
    # 其他砖经此取 agent 砖（含 agent_tools/register_tool 等能力），自行访问 capabilities。
    return registry.get("agent")
