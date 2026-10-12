# -*- coding: utf-8 -*-
"""诊断实验：复现 palm-chat 逗号级碎片化请求 vs 整句单请求的延迟与音频质量对比。

用法: python diag_latency.py  (服务须已在 127.0.0.1:10080 就绪)
"""
import argparse
import json
import re
import sys
import time
import urllib.request
import wave

import numpy as np

AP = argparse.ArgumentParser()
AP.add_argument("--port", type=int, default=10080)
AP.add_argument("--ref", default="refer_audio.wav")
AP.add_argument("--prompt-text", default="你好，我是语音助手。")
AP.add_argument("--out", default="diag_whole.wav")
AP.add_argument("--skip-frag", action="store_true", help="只跑整句模式")
ARGS = AP.parse_args()

BASE = f"http://127.0.0.1:{ARGS.port}/tts"
REF_WAV = ARGS.ref
PROMPT_TEXT = ARGS.prompt_text

# 典型 LLM 回复文本（多句多逗号）
TEXT = ("好的呀，我现在就帮你处理这个问题。首先我们需要确认一下参数设置，"
        "然后再进行下一步操作。如果中间遇到什么报错，我会及时告诉你的。"
        "整个过程大概需要几分钟，请耐心等待一下哦。")

SPLIT_RE = re.compile(r"[。！？；…]+|[,，]")  # 与 chat_service._SENTENCE_SPLIT 一致


def tts(text: str, streaming: bool = False, out: str | None = None) -> dict:
    payload = json.dumps({
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": REF_WAV,
        "prompt_text": PROMPT_TEXT,
        "prompt_lang": "zh",
        "text_split_method": "cut0",
        "media_type": "wav",
        "streaming_mode": streaming,
    }).encode("utf-8")
    req = urllib.request.Request(BASE, data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as resp:
        first = None
        body = bytearray()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            if first is None:
                first = time.perf_counter() - t0
            body.extend(chunk)
    total = time.perf_counter() - t0
    if out:
        with open(out, "wb") as f:
            f.write(bytes(body))
    return {"ttfb": first, "total": total, "bytes": len(body)}


def wav_stats(path: str) -> dict:
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    dur = n / sr
    # 检测静音段（RMS 窗 50ms，阈值 1% 满幅）
    win = int(sr * 0.05)
    nwin = len(data) // win
    rms = np.sqrt(np.mean(data[: nwin * win].reshape(nwin, win) ** 2, axis=1))
    silent = rms < 327.0
    gaps = []
    run = 0
    for s in silent:
        run = run + 1 if s else 0
        if run == 6:  # 连续 300ms 静音
            gaps.append(round(run * 0.05, 2))
        elif run > 6:
            gaps[-1] = round(run * 0.05, 2)
    return {"sr": sr, "dur": round(dur, 2), "silence_gaps_300ms_plus": gaps}


def main() -> None:
    frags = [s for s in SPLIT_RE.split(TEXT) if s.strip()]
    print(f"文本 {len(TEXT)} 字，palm-chat 规则切出 {len(frags)} 个碎片: {frags}")
    print()

    if not ARGS.skip_frag:
        print("=== 模式A：碎片化逐请求（复现 palm-chat）===")
        t0 = time.perf_counter()
        for i, f in enumerate(frags):
            r = tts(f)
            print(f"  碎片{i + 1} [{f[:12]}…] TTFB={r['ttfb']:.2f}s total={r['total']:.2f}s size={r['bytes'] // 1024}KB")
        a_total = time.perf_counter() - t0
        print(f"  → 碎片模式总耗时: {a_total:.2f}s")
        print()

    print("=== 模式B：整句单请求（cut0）===")
    r = tts(TEXT, out=ARGS.out)
    print(f"  TTFB={r['ttfb']:.2f}s total={r['total']:.2f}s size={r['bytes'] // 1024}KB")
    print()

    st = wav_stats(ARGS.out)
    print("=== 整句输出 WAV 体检 ===")
    print(f"  采样率 {st['sr']} | 时长 {st['dur']}s")
    print(f"  ≥300ms 静音段: {st['silence_gaps_300ms_plus']}")


if __name__ == "__main__":
    main()
