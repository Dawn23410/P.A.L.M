# -*- coding: utf-8 -*-
"""加解密内核 C 后端并发基准：大文件低并发 + 小文件高并发（tp999）。

前提：palm_cryptokernel.backends 已探测到 C 后端（tongsuopy/铜锁）。
- 大文件低并发：vault.file_ops（含磁盘 IO），1MB/10MB/100MB，并发 1；10MB 追加并发 4。
- 小文件高并发：①MemoryCipher 典型记忆条目(~600B) ②vault.encrypt/decrypt_data 1KB，
  线程 1/8/32，每档 6000 op，per-op 延迟取 p50/p95/p99/tp999。

诚实标注：tongsuopy 为 pyca 风格绑定，update() 期间是否释放 GIL 未做保证——
并发扩展性以实测为准（聚合吞吐随线程数的变化直接反映 GIL 影响）。
"""
from __future__ import annotations
import os

import json
import shutil
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from palm_cryptokernel import MemoryCipher, Sm4Cipher, backends, vault

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_concurrency_tp999.json")
RESULT: dict = {"backend": backends.backend_name(), "large": {}, "small": {}}


def pct(sorted_lat_ms: list[float], q: float) -> float:
    """q 分位数（0.999 = tp999）。"""
    idx = max(0, min(len(sorted_lat_ms) - 1, int(round(q * len(sorted_lat_ms) + 0.5)) - 1))
    return round(sorted_lat_ms[idx], 4)


def summarize(lats_ms: list[float]) -> dict:
    s = sorted(lats_ms)
    return {"n": len(s), "p50": pct(s, 0.50), "p95": pct(s, 0.95),
            "p99": pct(s, 0.99), "tp999": pct(s, 0.999), "max": round(s[-1], 4)}


# ─────────────────── 大文件低并发（file_ops，含 IO） ───────────────────
def bench_large(tmp: str):
    print("=== 大文件低并发（vault.file_ops，含磁盘 IO）===")
    for size_mb in (1, 10, 100):
        src = os.path.join(tmp, f"f{size_mb}.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(size_mb * 1024 * 1024))
        runs = {1: 20, 10: 5, 100: 2}[size_mb]
        enc_l, dec_l = [], []
        for _ in range(runs):
            t0 = time.perf_counter(); e = vault.encrypt_file(src); enc_l.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter(); vault.decrypt_file(e, os.path.join(tmp, "out.bin")); dec_l.append((time.perf_counter() - t0) * 1000)
        for name, lat in ((f"encrypt_file {size_mb}MB", enc_l), (f"decrypt_file {size_mb}MB", dec_l)):
            s = summarize(lat)
            s["throughput_MBps"] = round(size_mb / (statistics.median(lat) / 1000), 1)
            RESULT["large"][name] = s
            print(f"  [并发1] {name:<22} p50={s['p50']:>9.2f}ms tp999={s['tp999']:>9.2f}ms "
                  f"({s['throughput_MBps']} MB/s, n={s['n']})")
        os.remove(src); os.remove(src + ".enc")

    # 10MB 并发 4：每任务独立源文件（.enc 输出路径不冲突）
    srcs = []
    for i in range(4):
        p = os.path.join(tmp, f"c4_{i}.bin")
        with open(p, "wb") as f:
            f.write(os.urandom(10 * 1024 * 1024))
        srcs.append(p)
    bar = threading.Barrier(4)

    def task(i):
        bar.wait()
        t0 = time.perf_counter()
        e = vault.encrypt_file(srcs[i])
        vault.decrypt_file(e, os.path.join(tmp, f"out4_{i}.bin"))
        return (time.perf_counter() - t0) * 1000

    with ThreadPoolExecutor(max_workers=4) as ex:
        lats = list(ex.map(task, range(4)))
    s = summarize(lats)
    s["throughput_MBps"] = round(40 / (statistics.median(lats) / 1000), 1)
    RESULT["large"]["10MB 并发4 (encrypt+decrypt)"] = s
    print(f"  [并发4] 10MB encrypt+decrypt       p50={s['p50']:>9.2f}ms tp999={s['tp999']:>9.2f}ms "
          f"({s['throughput_MBps']} MB/s 聚合, n={s['n']})")
    for p in srcs:
        os.remove(p); os.remove(p + ".enc")


# ─────────────────── 小文件高并发（tp999 主战场） ───────────────────
def _run_concurrent(fn, threads: int, total_ops: int) -> tuple[list[float], float]:
    """fn() 为单次操作；线程池均匀分摊 total_ops，逐 op 计时（ns 精度）。

    返回 (每 op 延迟列表 ms, 墙钟秒)。"""
    lats: list[float] = []
    lock = threading.Lock()
    bar = threading.Barrier(threads)

    def worker(k: int):
        own = []
        bar.wait()
        for _ in range(total_ops // threads):
            t0 = time.perf_counter_ns()
            fn(k)
            own.append((time.perf_counter_ns() - t0) / 1e6)
        with lock:
            lats.extend(own)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    t0 = time.perf_counter()
    [t.start() for t in ts]
    [t.join() for t in ts]
    return lats, time.perf_counter() - t0


def bench_small(tmp: str):
    print("\n=== 小文件高并发（per-op 延迟 tp999）===")
    memo = "用户说下周要交论文很焦虑，喜欢猫娘人设，讨厌被叫作 AI，最近在开发 P.A.L.M 项目。" * 3
    mc = MemoryCipher.from_key(Sm4Cipher.random_key())
    vault.set_master_key(os.urandom(16))
    kb = os.urandom(1024)
    total = 6000

    cases = {
        "MemoryCipher 600B 记忆条目 (enc+dec)": lambda i: mc.decrypt_text(mc.encrypt_text(memo)),
        "vault encrypt+decrypt_data 1KB": lambda i: vault.decrypt_data(vault.encrypt_data(kb)),
    }
    for name, fn in cases.items():
        for threads in (1, 8, 32):
            lats, wall = _run_concurrent(fn, threads, total)
            s = summarize(lats)
            s["ops_per_s"] = int(round(total / wall))
            RESULT["small"][f"{name} @{threads}T"] = s
            print(f"  {name:<38} @{threads:>2}T  p50={s['p50']:>7.3f}ms p95={s['p95']:>7.3f}ms "
                  f"p99={s['p99']:>7.3f}ms tp999={s['tp999']:>7.3f}ms  聚合 {s['ops_per_s']:>7} op/s")


def main():
    if backends.is_c_backend():
        print(f"后端: {backends.backend_name()}（C）\n")
    else:
        print("警告: 当前为纯 Python 后端，结果不代表 C 加速效果\n")
    tmp = tempfile.mkdtemp(prefix="vault_tp999_")
    vault.set_data_dir(tmp)
    vault.boot()
    bench_large(tmp)
    bench_small(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, ensure_ascii=False, indent=2)
    print(f"\n已写出 {OUT}")


if __name__ == "__main__":
    main()
