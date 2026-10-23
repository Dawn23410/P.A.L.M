"""MemoryCipher —— 记忆层落盘加密适配器（国密）。

对接 VectorMemory 的 `encrypt_text` / `decrypt_text` 接口：
- 默认 SM4-CBC 对称加密（密钥 16 字节，base64 文本输出，便于存 ChromaDB 文档/metadata）
- 可选 SM3 完整性标签：解密时校验，检测篡改/损坏（被篡改则返回空串而非错误内容）
- 可选 SM2 密钥信封：用 SM2 公钥加密 SM4 密钥后随数据存库，私钥离线保管
- `content_hash()`：用 SM3 产出稳定内容指纹，修复 Python `hash()` 跨进程随机化的隐患
  （ChromaDB 持久化跨进程，原生 hash() 受 PYTHONHASHSEED 影响，去重会失效）

安全边界（务必读懂，别当成"已加密就安全"）：
- 完整性标签是 **SM3 明文摘要**（非密钥 MAC），只能发现"损坏/误改"，
  **挡不住**能改写落盘数据的人——他重算标签即可。要抗篡改请用
  `vault.encrypt_data`（HMAC-SM3，加密后认证）。
- CBC 无认证，密钥复用同一 IV 会致命；本类**每次加密都用 os.urandom 新 IV**，
  且不提供"由调用方指定 IV"的入口（避免有人固定 IV 从而废掉整个方案）。
- 密钥文件以最小权限落盘（POSIX 0600 / Windows 走 icacls），见 _private_fs。
- `from_env` 的密钥对**同用户其它进程可见**（环境变量是进程级公开的），
  仅适合开发/临时场景，生产请用密钥文件或密钥库。

密钥来源优先级（构造方法）：
  - `from_key(bytes16)`            显式 16 字节密钥
  - `from_env("PALM_CRYPTO_KEY")`  环境变量 32 位 hex
  - `from_key_file(path)`          密钥文件（16 字节原始 或 32 字符 hex）
  - `generate(key_file=...)`        随机生成并写入 key 文件
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import _private_fs
from .sm3 import sm3_int
from .sm4 import _IV_LEN, Sm4Cipher


class MemoryCipher:
    TAG = "SM4$"

    def __init__(self, sm4_cipher: Sm4Cipher, integrity: bool = True):
        self._sm4 = sm4_cipher
        self._integrity = integrity

    # ---- 构造 ----
    @classmethod
    def from_key(cls, key: bytes, integrity: bool = True) -> "MemoryCipher":
        if len(key) != _IV_LEN:
            raise ValueError("密钥必须为 16 字节")
        return cls(Sm4Cipher(key), integrity=integrity)

    @classmethod
    def from_env(cls, env: str = "PALM_CRYPTO_KEY", integrity: bool = True) -> "MemoryCipher":
        raw = os.environ.get(env)
        if not raw:
            raise RuntimeError(f"环境变量 {env} 未设置（需 32 位 hex = 16 字节 SM4 密钥）")
        if len(raw) == 32:
            key = bytes.fromhex(raw)
        elif len(raw) == _IV_LEN:
            key = raw.encode("latin-1")
        else:
            raise ValueError("密钥格式应为 32 位 hex 或 16 字节原始串")
        return cls(Sm4Cipher(key), integrity=integrity)

    @classmethod
    def from_key_file(cls, path: str, integrity: bool = True) -> "MemoryCipher":
        p = Path(path)
        raw = p.read_bytes()
        if len(raw) == 32:  # hex 文本
            key = bytes.fromhex(raw.decode().strip())
        elif len(raw) == _IV_LEN:
            key = raw
        else:
            raise ValueError("密钥文件应为 16 字节原始密钥或 32 字符 hex")
        return cls(Sm4Cipher(key), integrity=integrity)

    @classmethod
    def generate(cls, key_file: Optional[str] = None, integrity: bool = True,
                 overwrite: bool = False) -> "MemoryCipher":
        """随机生成密钥；给了 key_file 就落盘（权限收紧，且默认**拒绝覆盖**）。

        WHY 拒绝覆盖：密钥文件被无声替换会让已落盘数据永久读不回，
        所以覆盖必须是调用方的显式意图（overwrite=True）。
        """
        key = Sm4Cipher.random_key()
        if key_file:
            target = Path(key_file)
            if target.exists() and not overwrite:
                raise FileExistsError(
                    f"密钥文件已存在，拒绝覆盖：{target}（确要覆盖请传 overwrite=True）")
            _private_fs.write_private_text(str(target), key.hex())
        return cls(Sm4Cipher(key), integrity=integrity)

    # ---- VectorMemory 接口 ----
    def encrypt_text(self, text: str) -> str:
        blob = self._sm4.encrypt_text(text)
        if self._integrity:
            digest = format(sm3_int(text) & 0xFFFFFFFF, "08x")
            return f"{self.TAG}{digest}:{blob}"
        return blob

    def decrypt_text(self, text: str) -> str:
        if self._integrity and text.startswith(self.TAG):
            tag, _, blob = text.partition(":")
            digest = tag[len(self.TAG):]
            plain = self._sm4.decrypt_text(blob)
            if format(sm3_int(plain) & 0xFFFFFFFF, "08x") != digest:
                # 完整性校验失败：宁可返回空也不返回被篡改内容
                return ""
            return plain
        return self._sm4.decrypt_text(text)

    # ---- 稳定内容指纹（修复 hash() 跨进程随机化）----
    def content_hash(self, text: str) -> int:
        # 掩 63 位正整，避免超出 ChromaDB/SQLite 的 64 位整数范围
        return sm3_int(text) & 0x7FFFFFFFFFFFFFFF
