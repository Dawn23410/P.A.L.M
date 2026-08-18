"""应用设置服务：设置持久化（收敛自 settings 砖）。

落盘到存储池根目录 settings.json，透明加密复用加解密适配器能力（单向依赖）；
自身文件缺失时经存储适配器一次性迁移旧设置，避免外观/Token 限额配置丢失。
同目录唯一临时文件 + 替换重试：规避 Windows 高频保存的并发写/杀软扫描共享冲突。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from palm._core.config import settings
from palm._core.paths import fallback_dir, resolve_storage
from palm._core.logging import get_logger
from palm._core.container import container

logger = get_logger(__name__)

SETTINGS_PATH = resolve_storage("settings.json", brick_file=__file__)


def _crypto_capabilities() -> tuple[object | None, object | None]:
    """仅经服务容器取加解密适配器能力，不 import 其内部模块。"""
    brick = container.get("crypto")
    if not brick:
        return (None, None)
    caps = getattr(brick, "capabilities", {}) or {}
    return (caps.get("encrypt_bytes"), caps.get("decrypt_bytes"))


def _is_encryption_enabled() -> bool:
    brick = container.get("crypto")
    if not brick:
        return False
    fn = (getattr(brick, "capabilities", {}) or {}).get("is_enabled")
    return bool(fn()) if callable(fn) else False


def load_app_settings() -> dict:
    """读取应用设置（JSON）；加密文件经加解密能力还原；损坏或缺失返回空字典。"""
    if not os.path.isfile(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "rb") as fh:
            raw = fh.read()
    except OSError:
        return {}
    _, decrypt_fn = _crypto_capabilities()
    if decrypt_fn is not None and _is_encryption_enabled():
        try:
            raw = decrypt_fn(raw)
            if raw is None:  # 密钥未就绪时降级为明文
                return {}
        except Exception:
            return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: str, content: bytes, max_retries: int = 6) -> None:
    # 固定名 .tmp 在并发请求时会因被其他写占用而 Errno 13 / 因目标被读占用而 WinError 32。
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        last_err: OSError | None = None
        for attempt in range(max_retries):
            try:
                os.replace(tmp, path)
                return
            except OSError as exc:
                # 共享冲突（目标被并发读取/锁）属瞬时，退避重试吸收；其余错误立即抛出。
                if getattr(exc, "winerror", None) == 32 or exc.errno in (13, 32):
                    last_err = exc
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        if last_err is not None:
            raise last_err
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def save_app_settings(payload: dict) -> None:
    """原子写：先落临时文件再 replace，避免半写损坏；加密开关开启时透明加密。"""
    if not isinstance(payload, dict):
        raise ValueError("设置必须是 JSON 对象")
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypt_fn, _ = _crypto_capabilities()
    if encrypt_fn is not None and _is_encryption_enabled():
        encrypted = encrypt_fn(content)
        if encrypted is not None:
            content = encrypted
    _atomic_write_json(SETTINGS_PATH, content)


def migrate_legacy_settings() -> None:
    """迁移桥：自身文件缺失时经存储适配器读旧设置写入本文件，仅触发一次。"""
    if os.path.isfile(SETTINGS_PATH):
        return
    storage = container.get("storage")
    if not storage:
        return
    loader = (getattr(storage, "capabilities", {}) or {}).get("load_app_settings")
    if not callable(loader):
        return
    try:
        old = loader() or {}
    except Exception:
        return
    if old:
        try:
            save_app_settings(old)
        except Exception:
            return
