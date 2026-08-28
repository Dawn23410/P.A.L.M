"""装配入口：把全部原子模块按依赖方向注入服务容器（唯一知道所有模块的地方）。

原则（评审决策）：
- 本模块是唯一出现「注册」概念的地方，业务模块零注册、零全局状态。
- 服务按名注册（storage/settings/crypto/models/usage/game/...），业务代码
  经 `container.get(名)` 惰性取用，缺失即 None（铁律：缺失归一降级）。
- 装配顺序即依赖顺序：先底座，再适配器，最后服务与领域。

本文件不启动任何 HTTP/进程服务——运行入口由宿主（后端/CLI）自行决定。
"""

from __future__ import annotations

from palm._core.container import container

# 已就绪的服务（模块导入即注册能力）；名称对齐旧 registry 的服务名，
# 使迁移后的业务代码（container.get("storage") 等）保持语义一致。
_READY: dict[str, object] = {}


def _register(name: str, impl: object, capabilities: dict | None = None) -> None:
    container.register(name, impl, capabilities)
    _READY[name] = impl


def build_app() -> ContainerProxy:
    """装配全部模块到容器；幂等（重复调用直接返回已注册容器）。"""
    if container.names():
        return ContainerProxy(container)

    # ── 适配器层（外部/IO，先注册，供上层消费） ──
    try:
        from palm.adapters.storage import pool as _storage_pool
        _register("storage", _storage_pool, {
            "store_file": getattr(_storage_pool, "store_file", None),
            "read_file_content": getattr(_storage_pool, "read_file_content", None),
            "find_config_file": getattr(_storage_pool, "find_config_file", None),
            "delete_file": getattr(_storage_pool, "delete_file", None),
            "get_store": getattr(_storage_pool, "get_store", None),
            "load_app_settings": getattr(_storage_pool, "load_app_settings", None),
        })
    except Exception as exc:  # noqa: BLE001 底座缺失降级：上层经 None 归一
        print(f"[bootstrap] storage 注册失败（降级）: {exc}")

    from palm.adapters.io import app_settings
    _register("settings", app_settings, {"load_app_settings": app_settings.load_app_settings})

    try:
        from palm.adapters.crypto import keystore
        from palm.adapters.crypto import operations as _crypto_ops
        keystore.boot()  # 指纹采集失败仅置禁用，不阻断装配
        _register("crypto", keystore, {
            "is_enabled": keystore.is_enabled,
            "encrypt_bytes": getattr(_crypto_ops, "encrypt_data", None),
            "decrypt_bytes": getattr(_crypto_ops, "decrypt_data", None),
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] crypto 注册失败（降级）: {exc}")

    try:
        from palm.adapters.model import provider as _provider
        _register("models", _provider, {
            "create_stream": getattr(_provider, "stream_chat", None),
            "is_model_file_capable": getattr(_provider, "is_model_file_capable", None),
            "file_handling_mode": getattr(_provider, "file_handling_mode", None),
            "model_supports_files": getattr(_provider, "is_model_file_capable", None),
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] models 注册失败（降级）: {exc}")

    try:
        from gui.adapters_gui import automation_orchestrator as _gui
        _register("gui", _gui)
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] gui 注册失败（降级）: {exc}")

    # ── 服务层 ──
    try:
        from palm.services.ops import token_usage as _usage
        _register("usage", _usage, {"check_quota": _usage.check_quota,
                                    "record_usage": _usage_record})
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] usage 注册失败（降级）: {exc}")

    from palm.services.ops import token_ledger as _ledger
    _register("usage_ledger", _ledger)

    from palm.services.ops import engine as _scheduler
    _register("scheduler", _scheduler)

    from palm.services.chat import conversation_store as _conv
    _register("conversations", _conv)

    from palm.domain.roleplay import game_service as _game
    _register("game", _game, {
        "award_chat_xp": _game.award_chat_xp,
        "award_plan_xp": _game.award_plan_xp,
        "has_item": _game.has_item,
        "unlock_item": _game.unlock_item,
        "purchase_item": _game.purchase_item,
    })

    from palm.domain.roleplay import affinity_engine as _affinity
    _register("affinity", _affinity)

    from palm.domain.roleplay import character as _roleplay
    _register("roleplay", _roleplay, {"roleplay_api": _roleplay})

    try:
        from memory.domain_memory import memory_writer as _memory
        _register("memory", _memory, {"memory_api": _memory})
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] memory 注册失败（降级）: {exc}")

    from palm.services.evolution import registry as _evo_registry
    _register("evolution", _evo_registry, {"evolution_api": _evo_registry})

    from palm.services.agent import core as _agent
    _register("agent", _agent)

    return ContainerProxy(container)


class ContainerProxy:
    """只读容器视图：外部拿到的装配产物，业务经 container 全局单例即可，无需本类。"""

    def __init__(self, c: Container):
        self._container = c

    def get(self, name: str):
        return self._container.get(name)

    def names(self) -> list[str]:
        return self._container.names()


def _usage_record(**kwargs) -> None:
    """记账转发：usage 服务薄封装（token_usage 只判配额，记账在 ledger）。"""
    from palm.services.ops.token_ledger import record_request
    record_request(**kwargs)
