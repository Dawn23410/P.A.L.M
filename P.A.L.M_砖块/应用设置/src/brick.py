"""settings 砖块：应用设置持久化。

承载「应用设置」这一独立功能：经 /api/settings 读写，落盘到存储池根目录下的
settings.json，并复用 crypto 砖的加密能力（单向依赖）做透明加密。

启动时若自身文件缺失，经 storage 砖的 load_app_settings 能力一次性迁移旧设置，
避免拆分后用户外观 / Token 限额配置丢失；迁移完成后本砖完全自包含。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from fastapi import APIRouter, Body, Depends, HTTPException

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])

# 独立落盘路径：存储池根目录下、不进入任何分类子目录，与 storage 砖完全解耦。
SETTINGS_PATH = resolve_storage("settings.json", brick_file=__file__)


def _crypto_capabilities() -> tuple[object | None, object | None]:
    # 砖块互不调用：仅经 registry 消费 crypto 砖暴露的加密能力，不 import 其内部模块。
    brick = registry.get("crypto")
    if not brick:
        return (None, None)
    caps = getattr(brick, "capabilities", {}) or {}
    return (caps.get("encrypt_bytes"), caps.get("decrypt_bytes"))


def _is_encryption_enabled() -> bool:
    brick = registry.get("crypto")
    if not brick:
        return False
    fn = (getattr(brick, "capabilities", {}) or {}).get("is_enabled")
    return bool(fn()) if callable(fn) else False


def load_app_settings() -> dict:
    # 读取应用设置（JSON）；加密文件经 crypto 能力还原；损坏或缺失返回空字典。
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
            if raw is None:  # crypto 能力返回 None（密钥未就绪），降级为明文
                return {}
        except Exception:
            return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: str, content: bytes, max_retries: int = 6) -> None:
    # 同目录唯一临时文件 + 替换重试：规避 Windows 下高频保存的并发写/杀软扫描共享冲突。
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
        # 替换失败时清理残留临时文件，避免堆积；忽略清理本身的异常。
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def save_app_settings(payload: dict) -> None:
    # 原子写：先落临时文件再 replace，避免半写损坏；加密开关开启时经 crypto 能力加密。
    if not isinstance(payload, dict):
        raise ValueError("设置必须是 JSON 对象")
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypt_fn, _ = _crypto_capabilities()
    if encrypt_fn is not None and _is_encryption_enabled():
        encrypted = encrypt_fn(content)
        if encrypted is not None:
            content = encrypted
    _atomic_write_json(SETTINGS_PATH, content)


def _migrate_once() -> None:
    # 拆分迁移桥：自身文件缺失时，经 storage 砖能力读旧设置写入本砖文件，仅触发一次。
    if os.path.isfile(SETTINGS_PATH):
        return
    storage_brick = registry.get("storage")
    if not storage_brick:
        return
    loader = (getattr(storage_brick, "capabilities", {}) or {}).get("load_app_settings")
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


_migrate_once()


@router.get("/settings", dependencies=[Depends(require_api_token)])
def get_settings() -> dict:
    """读取持久化的应用设置（外观、Token 限额等）；无则返回空对象。"""
    return load_app_settings()


@router.post("/settings", dependencies=[Depends(require_api_token)])
def post_settings(payload: dict = Body(...)) -> dict:
    """持久化应用设置到 settings.json；加密开关开启时自动加密落盘。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="设置必须是 JSON 对象")
    try:
        save_app_settings(payload)
    except (OSError, ValueError) as exc:
        # 转结构化 500：确保响应带 CORS 头（否则前端只看到 CORS 拦截，难以排查）。
        logger.warning("设置保存失败: %s", exc)
        raise HTTPException(status_code=500, detail="设置保存失败，请稍后重试")
    logger.info("应用设置已更新（key_count=%d）", len(payload))
    return {"saved": True}


brick = Brick(
    manifest=BrickManifest(
        name="settings",
        title="应用设置",
        description="应用设置的持久化与读取（外观、Token 限额等），独立落盘并复用加密能力。",
        bus_type="board",
    ),
    router=router,
    capabilities={"load_app_settings": load_app_settings},
)
registry.register(brick)