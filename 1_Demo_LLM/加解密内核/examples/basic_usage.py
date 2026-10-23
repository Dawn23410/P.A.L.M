"""palm_cryptokernel 基本用法示例（可直接运行：python examples/basic_usage.py）。

演示：内核族接口（能力清单 / 公钥信封）/ 旧接口（MemoryCipher / SM2 密钥信封）/
vault 文件级加解密。全程本机完成、无需外部服务；vault 数据目录指向临时目录，
不污染 ~/.palm_cryptokernel。

范围边界：本内核只做机密性 + 完整性，**不做数字签名、不做后量子、不做密钥协商**
（详见 palm_cryptokernel.abcs 的端口清单）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palm_cryptokernel import (  # noqa: E402
    MemoryCipher,
    Sm2Key,
    Sm4Cipher,
    families as f,
    sm3_hash,
    suite,
)
from palm_cryptokernel import vault  # noqa: E402


def demo_capabilities() -> None:
    print("== 能力清单（有什么、缺什么，如实披露）==")
    cap = suite.capabilities()
    print("族标签:", suite.labels())
    print("算法总数:", cap["total"], "| 缺口:", len(cap["absent"]))
    for fam, count in cap["counts"].items():
        print(f"  {fam:8s} {count:3d} 个（推荐 {suite.recommended(fam)}）")


def demo_sm3() -> None:
    print("== SM3 内容指纹 ==")
    print("SM3:", sm3_hash("用户偏好：喜欢猫娘"))


def demo_memory_cipher() -> None:
    print("== SM4 记忆落盘加密（对接 VectorMemory）==")
    # 生产环境应从环境变量 / 密钥文件取密钥，切勿硬编码
    cipher = MemoryCipher.from_key(b"0123456789abcdef")
    enc = cipher.encrypt_text("用户偏好：喜欢猫娘，讨厌被叫作 AI")
    print("密文:", enc[:56], "...")
    print("解密:", cipher.decrypt_text(enc))
    print("内容指纹(content_hash):", cipher.content_hash("同一段文本"))


def demo_envelope() -> None:
    print("== 公钥信封（SM2 封装数据密钥 + AEAD 加密正文）==")
    pk, sk = f.envelope.generate()                 # 默认 SM2（国密优先）
    blob = f.envelope.seal(pk, "任意长正文".encode(), aad="记录ID=42".encode())
    print("报文头:", f.envelope.peek(blob))
    print("解封还原:", f.envelope.open(sk, blob, aad="记录ID=42".encode()).decode())
    print("推荐组合:", f.envelope.recommend_pair())


def demo_sm2_envelope() -> None:
    print("== SM2 密钥信封（密钥与数据分离）==")
    sm2k = Sm2Key.generate()
    sm4_key = Sm4Cipher.random_key()
    wrapped = sm2k.encrypt(sm4_key)
    print("SM4 密钥:", sm4_key.hex())
    print("SM2 信封:", wrapped.hex()[:56], "...")
    print("还原密钥:", sm2k.decrypt(wrapped).hex())


def demo_vault() -> None:
    print("== vault 文件级加解密（硬件指纹密封密钥库）==")
    with tempfile.TemporaryDirectory() as d:
        vault.set_data_dir(d)                      # 须在 boot() 之前调用
        vault.boot()
        print("绑定状态:", vault.is_bound(), "| 指纹前缀:", vault.fingerprint_prefix())
        print("数据解密:", vault.decrypt_data(vault.encrypt_data("机密数据".encode("utf-8"))))
        src = Path(d, "report.txt")
        src.write_text("待加密的文件内容", encoding="utf-8")
        enc = vault.encrypt_file(str(src))
        print("加密文件:", os.path.basename(enc))
        print("还原内容:", Path(vault.decrypt_file(enc)).read_text(encoding="utf-8"))


def main() -> None:
    demo_capabilities()
    demo_sm3()
    demo_memory_cipher()
    demo_envelope()
    demo_sm2_envelope()
    demo_vault()
    print("\n全部示例执行完成。")


if __name__ == "__main__":
    main()
