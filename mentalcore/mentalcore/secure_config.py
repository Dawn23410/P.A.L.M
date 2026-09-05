"""安全配置存储：API 密钥等敏感配置以 SM4 加密 JSON 落盘（替代明文 .env/json）。

用法：
    from .secure_config import save_api_secret, load_api_secret
    crypto = CryptoProvider(enabled=True, master_key_file=KEY_FILE)
    save_api_secret("api_secret.json", {"base_url": ..., "api_key": ...}, crypto)
    conf = load_api_secret("api_secret.json", crypto)   # 解密还原 dict

设计要点：
- 密文落盘：明文密钥不写盘；主密钥在 master_key_file（本机 ACL 内）。
- 接口简单：只做「加密 JSON ⇄ dict」，不绑定业务结构，可存任意敏感配置。
- 文件权限：写入时提示收紧 ACL（Windows 可 icacls 限当前用户）。
"""
from __future__ import annotations

import json
import os

from .crypto_provider import CryptoProvider


def save_api_secret(path: str, payload: dict, crypto: CryptoProvider) -> None:
    """把敏感配置 dict 加密写入 JSON 文件（SM4 密文）。"""
    if not getattr(crypto, "enabled", True):
        raise RuntimeError("加密未启用，拒绝明文落盘敏感配置")
    blob = crypto.encrypt_text(json.dumps(payload, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as f:
        f.write(blob)
    try:
        os.chmod(path, 0o600)  # 尽力收紧权限（Windows 主要靠 ACL，此处尽力）
    except OSError:
        pass


def load_api_secret(path: str, crypto: CryptoProvider) -> dict:
    """读取并解密敏感配置 JSON，还原 dict。"""
    with open(path, "r", encoding="utf-8") as f:
        blob = f.read().strip()
    text = crypto.decrypt_text(blob)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("加密配置内容必须为对象（JSON dict）")
    return data


def open_with_master_key(path: str, key_file: str) -> dict:
    """便捷入口：用本地主密钥文件直接读取加密配置（装配方一行接入）。"""
    crypto = CryptoProvider(enabled=True, key_file=key_file)
    return load_api_secret(path, crypto)


def config_from_secret(path: str, key_file: str) -> dict:
    """从加密配置构造 Config 装配字典（base_url/api_key/model…，缺省项自动跳过）。"""
    secret = open_with_master_key(path, key_file)
    out = {}
    for key in ("base_url", "api_key", "model", "provider_mode",
                "temperature", "max_tokens", "mode"):
        if key in secret and secret[key] not in (None, ""):
            out[key] = secret[key]
    return out
