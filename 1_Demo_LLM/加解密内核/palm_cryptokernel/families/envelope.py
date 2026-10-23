"""信封族：**公钥信封**（公钥封装数据密钥 + AEAD 加密正文）。

为什么需要它：公钥加密只能处理短数据（RSA-2048 上限约 190 字节），而实际要传的是
任意长内容。本族把两步拼成一个动作，是"给某人发一段加密数据"的标准姿势：

    pk, sk = envelope.generate()                       # 默认 SM2（国密）
    blob   = envelope.seal(pk, b"任意长的正文", aad=b"记录ID=42")
    plain  = envelope.open(sk, blob, aad=b"记录ID=42")

为什么这么设计（WHY）：
    数据密钥 = 随机生成（每条报文独立，不跨报文复用）
    wrapped  = pubkey.encrypt(pk, 数据密钥)     ← 只有持私钥者能取回
    nonce    = 随机（每条报文独立）
    sealed   = AEAD.seal(数据密钥, nonce, 正文, aad)
正文只经对称 AEAD，故公钥侧的开销与正文长度无关；数据密钥与 nonce 都**逐条新生成**，
从结构上杜绝"同一密钥配同一 nonce"这类致命误用。

报文格式（大端，全部长度前缀；密文自描述，无需外部元数据）：
    magic(4B)=b"PKEN" | ver(1B) | pub_len(1B) | aead_len(1B) | nonce_len(1B)
    | pub(变长 ascii) | aead(变长 ascii) | nonce(变长) | wk_len(2B) | wrapped | sealed
"""
from __future__ import annotations

import secrets
import struct

from ..errors import CryptoError, KeyFormatError
from ..registry import registry
from ._util import BytesLike, as_bytes

MAGIC = b"PKEN"
VERSION = 2                 # v1 是已废弃的后量子（KEM）报文，格式不同且不再支持
DEFAULT_PUBKEY = "sm2"      # 国密优先；用 RSA 需显式指定
DEFAULT_AEAD = "aes-256-gcm"

_HEADER = struct.Struct(">4sBBBB")


def generate(pubkey: str = DEFAULT_PUBKEY) -> tuple[bytes, bytes]:
    """按公钥算法生成信封密钥对，返回 (公钥, 私钥)。"""
    return registry.get("pubkey", pubkey).generate()


def _pick(aead: str | None) -> str:
    """选 AEAD：显式指定优先，否则用 aead 族推荐值。"""
    from . import aead as _aead
    return aead or _aead.recommended()


def seal(public_key: BytesLike, plaintext: BytesLike, *,
         aad: BytesLike = b"", pubkey: str = DEFAULT_PUBKEY,
         aead: str | None = None) -> bytes:
    """封装 + 加密：返回自描述密文报文。"""
    from . import aead as _aead
    pub_algo = registry.get("pubkey", pubkey)
    aead_name = _pick(aead)
    aead_algo = registry.get("aead", aead_name)

    pk = as_bytes(public_key, field="公钥")
    key_len = aead_algo.key_size()
    limit = _max_plaintext(pub_algo, pk)
    if limit and key_len > limit:
        raise KeyFormatError(f"{pubkey} 装不下 {key_len} 字节数据密钥（上限 {limit}）")

    data_key = secrets.token_bytes(key_len)          # 逐条独立
    nonce = _aead.new_nonce_for(aead_name)           # 逐条独立
    wrapped = pub_algo.encrypt(pk, data_key)
    sealed = _aead.seal(aead_name, data_key, nonce, plaintext, aad)

    pub_bytes, aead_bytes = pubkey.encode(), aead_name.encode()
    _check_short(len(pub_bytes), "pubkey 名")
    _check_short(len(aead_bytes), "aead 名")
    if not 0 < len(wrapped) < 0x10000:
        raise CryptoError(f"封装后的数据密钥长度越界：{len(wrapped)}")
    header = _HEADER.pack(MAGIC, VERSION, len(pub_bytes), len(aead_bytes), len(nonce))
    return (header + pub_bytes + aead_bytes + nonce
            + struct.pack(">H", len(wrapped)) + wrapped + sealed)


def open(secret_key: BytesLike, blob: BytesLike, *,
         aad: BytesLike = b"") -> bytes:
    """校验报文头 → 解封数据密钥 → 解密正文；任一步失败抛 CryptoError 子类。"""
    from . import aead as _aead
    data = as_bytes(blob, field="信封密文")
    pubkey, aead_name, nonce, wrapped, sealed = _parse(data)

    data_key = registry.get("pubkey", pubkey).decrypt(
        as_bytes(secret_key, field="私钥"), wrapped)
    return _aead.open(aead_name, data_key, nonce, sealed, aad)


def peek(blob: BytesLike) -> dict:
    """只读报文头（不解密），用于路由/审计/排查。"""
    pubkey, aead_name, nonce, wrapped, sealed = _parse(as_bytes(blob, field="信封密文"))
    return {"version": VERSION, "pubkey": pubkey, "aead": aead_name,
            "nonce_size": len(nonce), "wrapped_key_size": len(wrapped),
            "sealed_size": len(sealed)}


def _max_plaintext(algo: object, public_key: bytes) -> int:
    """公钥算法声明的明文上限；未声明（如 SM2）返回 0 表示"不适用"。"""
    probe = getattr(algo, "max_plaintext", None)
    return int(probe(public_key)) if callable(probe) else 0


def _check_short(length: int, field: str) -> None:
    """算法名长度必须装进 1 字节头字段。"""
    if not 1 <= length <= 255:
        raise CryptoError(f"信封头的 {field} 长度越界：{length}")


def _parse(data: bytes) -> tuple[str, str, bytes, bytes, bytes]:
    """拆解报文：返回 (pubkey, aead, nonce, wrapped, sealed)；格式非法即报错。"""
    if len(data) < _HEADER.size:
        raise KeyFormatError("信封密文过短，缺少报文头")
    magic, ver, plen, alen, nlen = _HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise KeyFormatError("信封密文标识不符（magic 非 PKEN）")
    if ver != VERSION:
        raise CryptoError(f"不支持的信封报文版本：{ver}")
    pos = _HEADER.size
    pub_b, aead_b = data[pos:pos + plen], data[pos + plen:pos + plen + alen]
    pos += plen + alen
    nonce = data[pos:pos + nlen]
    pos += nlen
    if len(nonce) != nlen or len(data) < pos + 2:
        raise KeyFormatError("信封密文被截断（头部声明的长度与实际不符）")
    wk_len = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    wrapped, sealed = data[pos:pos + wk_len], data[pos + wk_len:]
    if len(wrapped) != wk_len:
        raise KeyFormatError("信封密文被截断（封装的密钥长度不足）")
    try:
        return pub_b.decode(), aead_b.decode(), nonce, wrapped, sealed
    except UnicodeDecodeError as exc:
        raise KeyFormatError(f"信封头算法名非 ASCII：{exc}") from exc


def recommend_pair(*, guomi: bool = True) -> dict[str, str]:
    """推荐算法组合（供 UI/配置展示与优选）。默认国密 SM2。"""
    from . import aead as _aead, pubkey as _pubkey
    return {"pubkey": _pubkey.recommended(guomi=guomi),
            "aead": _aead.recommended()}


__all__ = ["MAGIC", "VERSION", "DEFAULT_PUBKEY", "DEFAULT_AEAD",
           "generate", "seal", "open", "peek", "recommend_pair"]
