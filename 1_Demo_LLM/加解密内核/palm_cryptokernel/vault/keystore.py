"""加密芯片密钥库管理（自 P.A.L.M `palm/adapters/crypto` 收敛而来）。

主密钥（16 字节）以硬件指纹派生的密钥密封落盘（密钥库），仅本机可自动解封；
32 位 hex 即恢复密钥，可脱离硬件解密数据。指纹采集失败时整体禁用，
加解密操作由同目录 operations 承载。

数据位置：`get_data_dir()/.keys/`（默认 PALM_CRYPTO_HOME 或 ~/.palm_cryptokernel；
P.A.L.M shim 会 set_data_dir() 钉回砖内，保持"砖可整体移动"语义）。
"""
from __future__ import annotations

import json
import logging
import os

from .. import _private_fs
from .operations import (
    ensure_checksum,
    get_data_dir,
    is_gmssl_available,
    recovery_checksum,
    seal_keystore,
    set_master_key,
    unseal_keystore,
)
from .fingerprint import (
    fingerprint_sources,
    fingerprint_strength,
    get_machine_fingerprint,
)

logger = logging.getLogger(__name__)


def _keystore_path() -> str:
    # 密钥库随数据目录内聚于 .keys/，以硬件指纹密封，仅本机可解封。
    return os.path.join(get_data_dir(), ".keys", ".crypto_keystore")


def _enabled_path() -> str:
    return os.path.join(get_data_dir(), ".keys", ".crypto_state.json")


_fingerprint: str = ""
_bind_ok: bool = False
_master_locked: bool = False
_enabled: bool = False


def _read_keystore() -> bytes | None:
    """返回主密钥；文件缺失返回 None（需新建），指纹不符抛 ValueError。"""
    if not os.path.exists(_keystore_path()):
        return None
    with open(_keystore_path(), "rb") as f:
        pkg = f.read()
    return unseal_keystore(pkg, _fingerprint)


def _write_keystore(master: bytes) -> None:
    """用当前指纹密封主密钥并落盘（目录 0700 / 文件 0600）。"""
    pkg = seal_keystore(master, _fingerprint)
    # 首次落盘前确保 .keys/ 存在（原实现缺失 mkdir，首次 boot 会 FileNotFoundError）
    _private_fs.ensure_dir(os.path.dirname(_keystore_path()))
    tmp = _keystore_path() + ".tmp"
    _private_fs.write_private_bytes(tmp, pkg)      # 临时文件同样最小权限
    os.replace(tmp, _keystore_path())
    _private_fs.restrict_file(_keystore_path())


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
        with open(_enabled_path(), "r", encoding="utf-8") as f:
            _enabled = bool(json.load(f).get("enabled", False))
    except (FileNotFoundError, ValueError):
        _enabled = False


def _set_enabled(value: bool) -> None:
    # 翻转开关并持久化；写盘失败仅告警，不影响内存态。
    global _enabled
    _enabled = bool(value)
    try:
        with open(_enabled_path(), "w", encoding="utf-8") as f:
            json.dump({"enabled": _enabled}, f)
    except OSError:
        logger.warning("加密开关状态持久化失败")


_HARDEN_TARGETS = (".crypto_keystore", ".recovery_checksum", ".crypto_state.json")


def _harden_paths() -> None:
    """把密钥库目录与其中的敏感文件权限收紧到仅本用户（best-effort，如实告警）。

    WHY 单独一步：密钥库可能由历史版本以默认权限落盘，启动时补收紧一次；
    收紧失败必须说出来，不能让调用方以为已经收紧了。

    WHY 走 `*_once`：目录收紧带 `(OI)(CI)` 继承位，后续新建文件自动继承；两者都
    进程内缓存，因此同进程重复 boot 不再付 icacls 子进程开销（原先每次 3–4 次）。
    """
    d = os.path.dirname(_keystore_path())
    if not os.path.isdir(d):
        return
    ok = _private_fs.harden_dir_once(d)
    for name in _HARDEN_TARGETS:
        ok = _private_fs.harden_file_once(os.path.join(d, name)) and ok
    if not ok:
        logger.warning("密钥库目录权限收紧未完全生效（Windows 需 icacls 可用；"
                       "当前保护仅依赖父目录 ACL）")


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
    """装配时调用一次：绑定指纹并加载密钥库与开关（失败仅降级禁用）。

    兜底 RuntimeError（指纹/gmssl 缺失）与 OSError（磁盘满/权限/路径不可写）——
    任一失败都降级禁用而非炸穿调用方，兑现"失败仅降级"的设计承诺。
    """
    global _fingerprint
    try:
        if not is_gmssl_available():
            raise RuntimeError("gmssl 国密库缺失")
        _fingerprint = get_machine_fingerprint()
        _load_or_create_keystore()
        _load_enabled()
        _harden_paths()
        # 只报指纹强度与来源，不报校验码/密钥（日志会外流）
        logger.info("主密钥就绪（指纹强度=%s 来源=%s）",
                    fingerprint_strength(), ",".join(fingerprint_sources()))
        if fingerprint_strength() != "per-unit":
            logger.warning("指纹仅为型号级：同型号机器可复现同一指纹，"\
                           "密钥库不具备跨机隔离强度")
    except (RuntimeError, OSError, ValueError) as exc:
        logger.error("加密芯片禁用（装配失败降级）: %s", type(exc).__name__)
