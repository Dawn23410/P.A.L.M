#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""声纹识别砖基准测试（对齐 GSV/CosyVoice 砖的 PALM砖块基准测试 惯例）。

测三项：
1. 磁盘占用 —— 砖目录整体（含 venv + CAM++ 权重）walk 求和。
2. VRAM —— CPU 砖，无显存占用，记 "N/A"。
3. Smoke —— 在 .venv-speaker 子进程内加载 CAM++ 并提取一条检验集的嵌入，
           记录加载耗时与提嵌耗时，验证引擎可独立启动。

用法（系统 Python 即可，内部自动用砖自带 venv）：
    python 声纹识别_bench.py
"""
import json
import os
import subprocess
import sys
import time

BRICK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEAKER_DIR = os.path.join(BRICK_DIR, "声纹识别")
VENV_PY = os.path.join(SPEAKER_DIR, ".venv-speaker", "Scripts", "python.exe")
MODEL_PATH = os.path.join(SPEAKER_DIR, "src", "speaker_models", "campplus_zh_en_fp16.onnx")
TEST_WAV = os.path.join(SPEAKER_DIR, "test_data", "spkA_1.wav")
SRC_DIR = os.path.join(SPEAKER_DIR, "src")


def measure_disk(path):
    """walk 求目录总字节数。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total


def run_smoke():
    """在砖自带 venv 子进程内加载 CAM++ 并提取嵌入，返回计时与维度。"""
    if not os.path.exists(VENV_PY):
        return {"ok": False, "reason": "venv 缺失: " + VENV_PY}
    if not os.path.exists(TEST_WAV):
        return {"ok": False, "reason": "检验集缺失: " + TEST_WAV}

    # 子进程内联脚本：插入 src 路径后复用 speaker_core，避免重复实现。
    payload = (
        "import sys, time, json\n"
        "sys.path.insert(0, r'%s')\n"
        "from speaker_core import SpeakerExtractor\n"
        "t0 = time.perf_counter()\n"
        "ex = SpeakerExtractor(model_path=r'%s', num_threads=4)\n"
        "t_load = (time.perf_counter() - t0) * 1000\n"
        "t1 = time.perf_counter()\n"
        "emb = ex.compute_from_wav(r'%s')\n"
        "t_emb = (time.perf_counter() - t1) * 1000\n"
        "print(json.dumps({'ok': True, 'dim': len(emb),\n"
        "                   'load_ms': round(t_load, 1),\n"
        "                   'embed_ms': round(t_emb, 1)}))\n"
    ) % (SRC_DIR, MODEL_PATH, TEST_WAV)

    proc = subprocess.run(
        [VENV_PY, "-c", payload],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        return {"ok": False, "reason": proc.stderr.strip()[:500]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "解析失败: %s | out=%s" % (exc, proc.stdout[:300])}


def main():
    disk_bytes = measure_disk(SPEAKER_DIR)
    smoke = run_smoke()
    result = {
        "brick": "声纹识别",
        "name": "speaker",
        "device": "cpu",
        "vram": "N/A",
        "disk_kb": round(disk_bytes / 1024, 1),
        "disk_bytes": disk_bytes,
        "model": os.path.basename(MODEL_PATH),
        "smoke": smoke,
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "声纹识别_result.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
