"""crypto 砖块：本机硬件指纹绑定加解密。

恢复密钥：主密钥（16 字节）的 32 位 hex 即恢复密钥，可脱离硬件解密数据；
主密钥以硬件指纹派生的密钥密封落盘（密钥库），仅本机可自动解封。

端点：
- GET  /api/crypto/status                 绑定状态 & 指纹前缀 & 算法细节
- POST /api/crypto/encrypt                加密文件 → .enc
- POST /api/crypto/decrypt                解密 .enc → 明文
- POST /api/crypto/encrypt-text           加密文本 → base64 密文
- POST /api/crypto/decrypt-text           解密 base64 密文 → 明文
- GET  /api/crypto/recovery-key           返回恢复密钥（32 hex）与校验码（8 hex）
- GET  /api/crypto/recovery-checksum       返回校验码（8 hex，独立于密钥库解封）
- POST /api/crypto/recovery-key/import    用恢复密钥重新绑定本机（仅校验主密钥格式）

指纹采集失败时降级：注册空砖（无路由），不阻塞应用启动。
"""
from __future__ import annotations

from palm_sdk.bricks._shared.paths import brick_local

import base64
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry

logger = get_logger(__name__)
from .file_ops import decrypt_file, encrypt_file
from .fingerprint import get_machine_fingerprint
from .operations import (
    _read_checksum,
    decrypt_data,
    ensure_checksum,
    encrypt_data,
    get_master_key,
    is_gmssl_available,
    recovery_checksum,
    seal_keystore,
    set_master_key,
    unseal_keystore,
)

router = APIRouter(prefix="/api/crypto", tags=["crypto"])

# 密钥库随砖内聚于 .keys/，以硬件指纹密封，仅本机可解封；砖可随意移动。
_KEYSTORE_PATH = brick_local(__file__, ".keys", ".crypto_keystore")

_fingerprint: str = ""
_bind_ok: bool = False
_master_locked: bool = False


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
    # 恢复密钥的 8 位 hex 校验码：首次绑定时随机生成，独立持久化到 backend/.recovery_checksum，
    # 与主密钥无派生关系，凭恢复密钥（32hex 主密钥明文）即可推导主密钥。
    ensure_checksum()
    _bind_ok = True


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


# 加密总开关（默认关闭）：仅开启后写入存储池的文件才加密，且开启时全量加密现有明文。
_ENABLED_PATH = brick_local(__file__, ".keys", ".crypto_state.json")
_enabled: bool = False


def _load_enabled() -> None:
    # 开关状态非敏感，明文 JSON 持久化；缺失或损坏一律回退到默认关闭。
    global _enabled
    try:
        with open(_ENABLED_PATH, "r", encoding="utf-8") as f:
            _enabled = bool(json.load(f).get("enabled", False))
    except (FileNotFoundError, ValueError):
        _enabled = False


def _set_enabled(value: bool) -> None:
    # 翻转开关并持久化；写盘失败仅告警，不影响内存态，避免阻塞用户操作。
    global _enabled
    _enabled = bool(value)
    try:
        with open(_ENABLED_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": _enabled}, f)
    except OSError:
        logger.warning("加密开关状态持久化失败")


try:
    if not is_gmssl_available():
        raise RuntimeError("gmssl 国密库缺失")
    _fingerprint = get_machine_fingerprint()
    _load_or_create_keystore()
    _load_enabled()
    logger.info("主密钥就绪 checksum=%s", recovery_checksum())
except RuntimeError as e:
    logger.error("硬件指纹采集失败，加密砖块禁用: %s", e)


class FilePathRequest(BaseModel):
    path: str


class TextCryptoRequest(BaseModel):
    text: str


class DecryptTextRequest(BaseModel):
    ciphertext: str


class RecoveryKeyImport(BaseModel):
    key: str


def _require_bind() -> None:
    if not _bind_ok:
        raise HTTPException(503, detail="加解密不可用：本机硬件指纹绑定失败")


@router.get("/status", dependencies=[Depends(require_api_token)])
async def api_status():
    """返回加密砖块状态：是否绑定、指纹前缀、加密算法细节。"""
    return {
        "bound": _bind_ok,
        "fingerprint_prefix": _fingerprint[:16] if _fingerprint else None,
        "algorithm": "SM4-CBC",
        "key_derivation": "主密钥（恢复密钥）经 PBKDF2-HMAC-SHA256 由硬件指纹密封",
        "integrity": "HMAC-SM3 签名校验",
    }


@router.post("/encrypt", dependencies=[Depends(require_api_token)])
async def api_encrypt(req: FilePathRequest):
    """加密指定文件，生成 .enc 文件。"""
    _require_bind()
    try:
        path = req.path
        if path.endswith(".enc"):
            raise HTTPException(400, detail="文件已是加密格式，请勿再次加密")
        enc_path = encrypt_file(path)
        return {"status": "success", "encrypted_file": enc_path}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, detail="加密失败，请检查文件权限")


@router.post("/decrypt", dependencies=[Depends(require_api_token)])
async def api_decrypt(req: FilePathRequest):
    """解密 .enc 文件，自动命名明文输出。"""
    _require_bind()
    try:
        path = req.path
        if not path.endswith(".enc"):
            raise HTTPException(400, detail="仅支持扩展名为 .enc 的文件")
        out_path = decrypt_file(path)
        return {"status": "success", "decrypted_file": out_path}
    except ValueError:
        raise HTTPException(
            403,
            detail="解密失败：文件校验未通过（可能非本机加密或已被篡改）",
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, detail="解密失败，请检查文件完整性")


class TextEncryptResponse(BaseModel):
    ciphertext: str
    fingerprint_prefix: str


@router.post("/encrypt-text", response_model=TextEncryptResponse, dependencies=[Depends(require_api_token)])
async def api_encrypt_text(req: TextCryptoRequest):
    """加密文本，返回 base64 密文。"""
    _require_bind()
    try:
        raw = req.text.encode("utf-8")
        pkg = encrypt_data(raw)
        return {
            "ciphertext": base64.b64encode(pkg).decode("ascii"),
            "fingerprint_prefix": _fingerprint[:16],
        }
    except Exception:
        raise HTTPException(500, detail="文本加密失败")


class TextDecryptResponse(BaseModel):
    text: str


@router.post("/decrypt-text", response_model=TextDecryptResponse, dependencies=[Depends(require_api_token)])
async def api_decrypt_text(req: DecryptTextRequest):
    """解密 base64 密文，返回原始文本。"""
    _require_bind()
    try:
        pkg = base64.b64decode(req.ciphertext)
        raw = decrypt_data(pkg)
        return {"text": raw.decode("utf-8")}
    except ValueError:
        raise HTTPException(
            403,
            detail="解密失败：密文校验未通过（可能非本机加密或已被篡改）",
        )
    except Exception:
        raise HTTPException(500, detail="文本解密失败")


@router.get("/recovery-key", dependencies=[Depends(require_api_token)])
async def api_recovery_key():
    """返回恢复密钥（32 hex）与校验码（8 hex）；主密钥未就绪不可用。"""
    master = get_master_key()
    if master is None:
        raise HTTPException(503, detail="主密钥未就绪，无法读取恢复密钥")
    return {
        "key": master.hex(),
        "checksum": recovery_checksum(),
    }


@router.get("/recovery-checksum", dependencies=[Depends(require_api_token)])
async def api_recovery_checksum():
    """返回持久化的 8 位 hex 校验码（独立于密钥库解封，供前端比对展示）。"""
    return {"checksum": _read_checksum() or ""}


@router.post("/recovery-key/import", dependencies=[Depends(require_api_token)])
async def api_import_recovery_key(req: RecoveryKeyImport):
    """用恢复密钥重新绑定本机：仅校验主密钥格式后重封密钥库。"""
    global _bind_ok, _master_locked
    logger.warning("导入恢复密钥重新绑定本机（高危操作）")
    try:
        raw = req.key.strip().replace("-", "")
        master = bytes.fromhex(raw)
    except ValueError:
        raise HTTPException(400, detail="恢复密钥格式错误：应为 32 位十六进制")
    if len(master) != 16:
        raise HTTPException(400, detail="恢复密钥长度错误：应为 16 字节（32 位 hex）")
    set_master_key(master)
    try:
        _write_keystore(master)
    except Exception:
        raise HTTPException(500, detail="密钥库重新密封失败")
    _bind_ok = True
    _master_locked = False
    return {"status": "success"}


class EncryptionRequest(BaseModel):
    enabled: bool


def _storage_cap(name: str):
    # 经 registry 消费 storage 砖的全量加/解密能力，不跨砖 import 模块。
    brick = registry.get("storage")
    if not brick:
        return None
    return (getattr(brick, "capabilities", {}) or {}).get(name)


def _empty_gen():
    # storage 砖缺失时返回空生成器，前端仍能收到 done 事件正常收尾。
    return
    yield  # pragma: no cover


@router.get("/encryption", dependencies=[Depends(require_api_token)])
async def api_get_encryption():
    """返回加密总开关状态（默认关闭，开启后写入与存量均加密）。"""
    return {"enabled": _enabled, "bound": _bind_ok}


@router.post("/encryption", dependencies=[Depends(require_api_token)])
async def api_set_encryption(req: EncryptionRequest):
    """开启/关闭存储加密：以 SSE 流式回报进度，无退出概念，直到全部完成或出错。

    开启 → 全量加密现有明文文件；关闭 → 全量解密现有加密文件。
    """
    logger.warning("存储加密开关变更 enabled=%s（高危操作）", req.enabled)
    _require_bind()
    target = bool(req.enabled)

    def _sse(ev: dict) -> str:
        return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    def stream():
        gen = None
        try:
            if target:
                _set_enabled(True)
                gen = _storage_cap("encrypt_all_plaintext") or _empty_gen
            else:
                _set_enabled(False)
                gen = _storage_cap("decrypt_all_encrypted") or _empty_gen
            for ev in gen():
                yield _sse(ev)
            yield _sse({"type": "done", "enabled": target})
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _encrypt_bytes(plaintext: bytes) -> bytes | None:
    # 经 capabilities 暴露给 storage 砖消费；模块不可用时返回 None 让其降级明文。
    if not _bind_ok:
        return None
    try:
        return encrypt_data(plaintext)
    except Exception:
        return None


def _decrypt_bytes(pkg: bytes) -> bytes | None:
    if not _bind_ok:
        return None
    try:
        return decrypt_data(pkg)
    except Exception:
        return None


brick = Brick(
    manifest=BrickManifest(
        name="crypto",
        title="本机加解密",
        description="SM4 国密加解密，密钥绑定本机硬件指纹；凭恢复密钥可离线恢复。",
        bus_type="chip",
    ),
    router=router if _bind_ok else None,
    capabilities={
        "encrypt_bytes": _encrypt_bytes,
        "decrypt_bytes": _decrypt_bytes,
        "is_enabled": lambda: _enabled,
    },
)
registry.register(brick)