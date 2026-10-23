# -*- coding: utf-8 -*-
"""加解密内核 v0.2.0 统一加解密模块 · 速度基准 + 安全验证（生产就绪审计）。

速度：SM3 / Sm4Cipher(MemoryCipher 路径) / vault.operations(SM4+HMAC-SM3) /
     PBKDF2(200k) / SM2 信封 / boot() 装配 / file_ops 文件级 / 典型记忆条目延迟分布。
安全：篡改拒绝（密文/MAC/密钥/指纹）、IV 唯一性、明文不泄露、边界输入、
     常量时间 MAC 比较（代码审计项）。

输出：控制台全量数据 + bench_crypto_audit.json。全部为真实代码实测。
"""
from __future__ import annotations
import os

import json
import shutil
import statistics
import sys
import tempfile
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from palm_cryptokernel import MemoryCipher, Sm2Key, Sm4Cipher, sm3_hash, vault

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_crypto_audit.json")
RESULT: dict = {"speed": {}, "security": {}}


def ms_of(fn, n, *a, **k):
    """跑 n 次取延迟列表（ms）。"""
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn(*a, **k)
        lat.append((time.perf_counter() - t0) * 1000)
    return lat


def mbps(n_bytes: int, lat_ms: list[float]) -> float:
    med = statistics.median(lat_ms)
    return round(n_bytes / (med / 1000) / 1e6, 2)


def fmt(name: str, lat: list[float], payload: int = 0):
    row = {"p50_ms": round(statistics.median(lat), 3),
           "p95_ms": round(sorted(lat)[int(len(lat) * 0.95)], 3),
           "mean_ms": round(statistics.mean(lat), 3)}
    if payload:
        row["throughput_MBps"] = mbps(payload, lat)
    RESULT["speed"][name] = row
    extra = f" | {row['throughput_MBps']} MB/s" if payload else ""
    print(f"  {name:<44} p50={row['p50_ms']:>8.3f}ms  p95={row['p95_ms']:>8.3f}ms{extra}")
    return row


# ═══════════════════════ 速度基准 ═══════════════════════
def bench_speed():
    print("=== 速度基准 ===")
    kb = b"x" * 1024
    text_1k = "记" * 341  # ~1KB UTF-8

    # SM3
    lat = ms_of(lambda: sm3_hash(kb), 500)
    fmt("SM3 哈希 (1KB)", lat, 1024)

    # Sm4Cipher（MemoryCipher 底层，base64 落库路径）
    c = Sm4Cipher(Sm4Cipher.random_key())
    lat_e = ms_of(lambda: c.encrypt_text(text_1k), 300)
    ct = c.encrypt_text(text_1k)
    lat_d = ms_of(lambda: c.decrypt_text(ct), 300)
    fmt("SM4 encrypt_text (1KB, base64 落库)", lat_e, 1024)
    fmt("SM4 decrypt_text (1KB, base64 落库)", lat_d, 1024)

    # SM4 纯吞吐上限（64KB，无 base64）
    big = "记" * 32768  # 64KB UTF-8
    lat_e = ms_of(lambda: c.encrypt_text(big), 20)
    fmt("SM4 纯吞吐 (64KB, 含 base64)", lat_e, 65536)

    # MemoryCipher 典型记忆条目（~200 汉字 ≈ 600B UTF-8）
    mc = MemoryCipher.from_key(Sm4Cipher.random_key())
    memo = "用户说下周要交论文很焦虑，喜欢猫娘人设，讨厌被叫作 AI，最近在开发 P.A.L.M 项目。" * 3
    lat = ms_of(lambda: mc.encrypt_text(memo), 500)
    fmt("MemoryCipher 典型记忆条目 (~200字)", lat, len(memo.encode("utf-8")))

    # vault.operations（SM4-CBC + HMAC-SM3，主密钥路径）
    vault.set_master_key(os.urandom(16))
    lat_e = ms_of(lambda: vault.encrypt_data(kb), 300)
    pkg = vault.encrypt_data(kb)
    lat_d = ms_of(lambda: vault.decrypt_data(pkg), 300)
    fmt("vault encrypt_data (1KB, 含 HMAC-SM3)", lat_e, 1024)
    fmt("vault decrypt_data (1KB, 含 HMAC-SM3)", lat_d, 1024)

    # PBKDF2（密钥库密封要素）
    lat = ms_of(lambda: vault.derive_key("fp", os.urandom(16)), 3)
    fmt("PBKDF2-HMAC-SHA256 derive_key (200k 轮)", lat)

    # vault.boot() 装配（指纹采集 + 密钥库加载/生成 + 开关读取）
    tmp = tempfile.mkdtemp(prefix="vault_bench_")
    vault.set_data_dir(tmp)
    lat = ms_of(lambda: vault.boot(), 3)
    fmt("vault.boot() 装配 (含指纹+密钥库落盘)", lat)
    shutil.rmtree(tmp, ignore_errors=True)

    # SM2 信封（只作公钥加密原语：封/解 SM4 密钥；本内核不做签名）
    k = Sm2Key.generate()
    lat_e = ms_of(lambda: k.encrypt(kb), 50)
    env = k.encrypt(kb)
    lat_d = ms_of(lambda: k.decrypt(env), 50)
    fmt("SM2 信封加密 (1KB)", lat_e, 1024)
    fmt("SM2 信封解密 (1KB)", lat_d, 1024)

    # file_ops 文件级（1MB，含 IO + HMAC）
    tmp2 = tempfile.mkdtemp(prefix="vault_file_")
    src = os.path.join(tmp2, "big.bin")
    open(src, "wb").write(os.urandom(1024 * 1024))
    lat_e = ms_of(lambda: vault.encrypt_file(src), 5)
    enc = vault.encrypt_file(src)
    lat_d = ms_of(lambda: vault.decrypt_file(enc, os.path.join(tmp2, "out.bin")), 5)
    fmt("file_ops encrypt_file (1MB, 含 IO)", lat_e, 1024 * 1024)
    fmt("file_ops decrypt_file (1MB, 含 IO)", lat_d, 1024 * 1024)
    shutil.rmtree(tmp2, ignore_errors=True)


# ═══════════════════════ 安全验证 ═══════════════════════
def check_security():
    print("\n=== 安全验证 ===")
    sec = RESULT["security"]
    tmp = tempfile.mkdtemp(prefix="vault_sec_")
    vault.set_data_dir(tmp)
    vault.boot()
    key = vault.get_master_key()

    def record(name, ok, note=""):
        sec[name] = {"pass": bool(ok), "note": note}
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {note}")

    # S1/S2 篡改拒绝
    pkg = vault.encrypt_data("机密".encode())
    bad = bytearray(pkg); bad[len(pkg) // 2] ^= 0xFF
    try:
        vault.decrypt_data(bytes(bad)); record("S1 篡改密文拒绝", False)
    except ValueError:
        record("S1 篡改密文拒绝", True, "HMAC-SM3 拦截")
    bad = bytearray(pkg); bad[-1] ^= 0xFF
    try:
        vault.decrypt_data(bytes(bad)); record("S2 篡改 MAC 拒绝", False)
    except ValueError:
        record("S2 篡改 MAC 拒绝", True)

    # S3 错误密钥
    vault.set_master_key(os.urandom(16))
    try:
        vault.decrypt_data(pkg); record("S3 错误密钥拒绝", False)
    except ValueError:
        record("S3 错误密钥拒绝", True)
    vault.set_master_key(key)

    # S4 错误指纹解封
    sealed = vault.seal_keystore(key, "fp_machine_A")
    try:
        vault.unseal_keystore(sealed, "fp_machine_B"); record("S4 换机指纹解封拒绝", False)
    except ValueError:
        record("S4 换机指纹解封拒绝", True, "密钥库密封隔离")

    # S5 IV 唯一性（1000 次同明文加密）
    ivs = {vault.encrypt_data(b"k")[:16] for _ in range(1000)}
    record("S5 IV 唯一性 (1000 次)", len(ivs) == 1000, f"唯一 {len(ivs)}/1000")

    # S6 明文不泄露
    pt = ("机密记忆内容" * 20).encode()
    ct = vault.encrypt_data(pt)
    record("S6 密文不含明文字节", pt not in ct)

    # S7 MemoryCipher 篡改 → 空串
    mc = MemoryCipher.from_key(Sm4Cipher.random_key())
    e = mc.encrypt_text("敏感内容")
    bad = e[:-4] + ("AAAA" if e[-4:] != "AAAA" else "BBBB")
    record("S7 MemoryCipher 篡改返回空串", mc.decrypt_text(bad) == "")

    # S8 边界输入
    ok = all(vault.decrypt_data(vault.encrypt_data(p)) == p
             for p in (b"", b"x" * 16, os.urandom(1024 * 1024)))
    ok = ok and mc.decrypt_text(mc.encrypt_text("")) == ""
    record("S8 边界输入 (空/16B对齐/1MB)", ok)

    # S9 常量时间 MAC 比较（代码审计项）
    import inspect
    from palm_cryptokernel.vault import operations as ops
    src = inspect.getsource(ops.decrypt_data) + inspect.getsource(ops.unseal_keystore)
    record("S9 常量时间 MAC 比较", "compare_digest" in src and " mac != expected" not in src)

    # S10 恢复密钥路径（换机恢复）
    vault.set_master_key(bytes.fromhex(key.hex()))
    record("S10 恢复密钥导入路径", vault.decrypt_data(pkg) == "机密".encode())

    shutil.rmtree(tmp, ignore_errors=True)


def main():
    bench_speed()
    check_security()
    # 证据必须自述口径：换了后端/换库，数字含义就变了，所以后端与库版本都要记进产物
    import importlib.metadata as _md

    from palm_cryptokernel import backends

    def _ver(pkg: str) -> str:
        try:
            return _md.version(pkg)
        except Exception:      # 未安装的库不记为错误，标 missing
            return "missing"

    RESULT["env"] = {"python": sys.version.split()[0],
                     "backend": backends.backend_name(),
                     "c_backend": backends.is_c_backend(),
                     "gmssl": _ver("gmssl"),
                     "tongsuopy": _ver("tongsuopy"),
                     "platform": sys.platform}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, ensure_ascii=False, indent=2)
    print(f"\n已写出 {OUT}")


if __name__ == "__main__":
    main()
