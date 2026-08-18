"""加密芯片密钥库管理（收敛自 crypto 砖 brick 的 keystore 部分）。

主密钥（16 字节）以硬件指纹派生的密钥密封落盘（密钥库），仅本机可自动解封；
32 位 hex 即恢复密钥，可脱离硬件解密数据。指纹采集失败时整体禁用，
加解密操作由同目录 operations 承载。
"""
from __future__ import annotations

import json
import os

from palm._core.logging import get_logger
from palm._core.paths import brick_local
from .operations import (
    ensure_checksum,
    is_gmssl_available,
    recovery_checksum,
    seal_keystore,
    set_master_key,
    unseal_keystore,
)
from .fingerprint import get_machine_fingerprint

logger = get_logger(__name__)

# 密钥库随模块内聚于 .keys/，以硬件指纹密封，仅本机可解封；库可随意移动。
_KEYSTORE_PATH = brick_local(__file__, ".keys", ".crypto_keystore")
_ENABLED_PATH = brick_local(__file__, ".keys", ".crypto_state.json")

_fingerprint: str = ""
_bind_ok: bool = False
_master_locked: bool = False
_enabled: bool = False


def _read_keystore() -> bytes | None:
    """返回主密钥；文件缺失返回 None（需新建），指纹不符抛 ValueError。"""
    if not os.path.exists(_KEYSTORE_PATH):
        return None
    with open(_KEYSTORE_PATH, "rb") as f:
        pkg = f.read()
    return unseal_keystore(pkg, _fingerprint)


def _write_keystore(master: bytes) -> None:
    """用当前指纹密封主密钥并落盘。"""
    pkg = seal_keystore(master, _fingerprint)
    tmp = _KEYSTORE_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(pkg)
    os.replace(tmp, _KEYSTORE_PATH)


def _load_or_create_keystore() -> None:
    """启动时加载或生成主密钥，并封印至密钥库。"""
    global _bind_ok, _master_locked
    try:
        master = _read_keystore()
    except ValueError:
        # 指纹不匹配（换机）或密钥库损坏：等待用户导入恢复密钥。
        _master_locked = True
        _bind_ok = False
        logger.error("密钥库解封失败，需导入恢复密钥")
        return
    if master is None:
        master = os.urandom(16)
        _write_keystore(master)
    set_master_key(master)
    # 恢复密钥的 8 位 hex 校验码：首次绑定时随机生成，与主密钥无派生关系。
    ensure_checksum()
    _bind_ok = True


def _load_enabled() -> None:
    # 开关状态非敏感，明文 JSON 持久化；缺失或损坏一律回退到默认关闭。
    global _enabled
    try:
        with open(_ENABLED_PATH, "r", encoding="utf-8") as f:
            _enabled = bool(json.load(f).get("enabled", False))
    except (FileNotFoundError, ValueError):
        _enabled = False


def _set_enabled(value: bool) -> None:
    # 翻转开关并持久化；写盘失败仅告警，不影响内存态。
    global _enabled
    _enabled = bool(value)
    try:
        with open(_ENABLED_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": _enabled}, f)
    except OSError:
        logger.warning("加密开关状态持久化失败")


def is_bound() -> bool:
    return _bind_ok


def is_locked() -> bool:
    return _master_locked


def is_enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    _set_enabled(value)


def fingerprint_prefix() -> str:
    return _fingerprint[:16] if _fingerprint else ""


def boot() -> None:
    """装配时调用一次：绑定指纹并加载密钥库与开关（失败仅降级禁用）。"""
    global _fingerprint
    try:
        if not is_gmssl_available():
            raise RuntimeError("gmssl 国密库缺失")
        _fingerprint = get_machine_fingerprint()
        _load_or_create_keystore()
        _load_enabled()
        logger.info("主密钥就绪 checksum=%s", recovery_checksum())
    except RuntimeError as exc:
        logger.error("硬件指纹采集失败，加密芯片禁用: %s", exc)
