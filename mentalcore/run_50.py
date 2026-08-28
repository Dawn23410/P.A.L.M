#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""50 轮压测 wrapper（P.A.L.M 运营控制台压测）。

规则（用户需求）：
1. 完全模拟普通用户，不中途去后台找资料（除非炸了要改）。
2. 炸了立刻修改，修改完从头跑（计数器归零）。
3. 记录全流程资源占用 + 延迟。
4. 记录所有能记录的原始数据。
5. LLM 原始回答落盘但不打印（禁止在终端看 LLM 原本回答）。
6. 其中 5 轮为 stt-llm-tts 完整语音闭环（由外部 GSV server 提供），其余走简化版。

本文件负责：
- 简化版 45 轮（文字 -> LLM -> 记忆层），直接复用 chat_100 的 user_say / mengyao_reply。
- 每轮采集：整轮耗时、LLM 首字延迟、记忆检索耗时、宿主机侧资源（由外部采样器采，这里只记时间戳）。
- 原始数据落盘到 ./run50_data/：
    raw_rounds.jsonl      每轮结构化原始（输入/LLM原文/TTS待生成/记忆检索原始/资源占用占位）
    llm_raw/<round>.txt   LLM 原始回答文本（落盘不打印）
    stt_raw/<round>.txt   STT 识别文本（闭环轮）
    audio_in/<round>.wav  闭环轮：用户语音（TTS 合成）
    audio_out/<round>.wav 闭环轮：回答语音（TTS 合成）
- 严格不 print 梦瑶完整回答；仅打印轮次/延迟/好感度等元信息。

注意：本脚本在 palm:test 容器内从 /opt/palm/mentalcore 运行。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

# 复用 chat_100 的逻辑（同目录）
from chat_100 import user_say, mengyao_reply, CharacterCard, build_core, load_config

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "run50_data")
for sub in ("llm_raw", "stt_raw", "audio_in", "audio_out"):
    os.makedirs(os.path.join(DATA_DIR, sub), exist_ok=True)

OUT_ROUNDS = os.path.join(DATA_DIR, "raw_rounds.jsonl")
GSV_API_URL = os.environ.get("GSV_API_URL", "http://host.docker.internal:9880").rstrip("/")
RUN_VOICE = os.environ.get("RUN_VOICE", "0") == "1"  # 闭环轮开关（由外部置 1）


def _now_ms():
    return time.time() * 1000.0


def _gsv_tts(text: str, out_wav: str, refer_wav: str, refer_text: str) -> bool:
    """调 GSV server 合成语音。返回是否成功。"""
    try:
        import soundfile as sf  # noqa
    except Exception:
        pass
    payload = {
        "refer_wav_path": refer_wav,
        "prompt_text": refer_text,
        "prompt_language": "zh",
        "text": text,
        "text_language": "zh",
        "speed": 0.8,
    }
    try:
        with httpx.stream("POST", GSV_API_URL + "/", json=payload, timeout=120) as resp:
            resp.raise_for_status()
            chunks = b"".join(resp.iter_bytes(chunk_size=65536))
        with open(out_wav, "wb") as f:
            f.write(chunks)
        return True
    except Exception as e:
        print(f"  [TTS] 失败: {e!r}", flush=True)
        return False


def _vosk_recognize(model_dir: str, wav_path: str) -> str:
    """VOSK 识别 wav -> 文本。返回识别文本。"""
    try:
        import numpy as np
        from vosk import Model, KaldiRecognizer
        import soundfile as sf
        import wave
    except Exception as e:
        return f"[VOSK依赖缺失:{e}]"
    try:
        # 读原始数据，再线性插值重采样到 16k（不依赖 numpy.resample / soundfile 重采样）
        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]
        if sr != 16000:
            new_len = int(round(len(data) * 16000.0 / sr))
            x_old = np.linspace(0, len(data) - 1, len(data))
            x_new = np.linspace(0, len(data) - 1, new_len)
            data = np.interp(x_new, x_old, data).astype("float32")
        pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
        tmp = wav_path + ".16k.wav"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        model = Model(model_dir)
        rec = KaldiRecognizer(model, 16000)
        with open(tmp, "rb") as f:
            while True:
                d = f.read(4000)
                if not d:
                    break
                rec.AcceptWaveform(d)
        res = json.loads(rec.FinalResult())
        return res.get("text", "")
    except Exception as e:
        return f"[VOSK识别失败:{e}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=45)
    ap.add_argument("--voice-rounds", type=int, default=0,
                    help="其中多少轮做 stt-llm-tts 闭环（0=全简化版）")
    ap.add_argument("--refer-wav", type=str, default="",
                    help="GSV 参考音色音频（闭环轮用）")
    ap.add_argument("--refer-text", type=str, default="你好，我是语音助手。")
    ap.add_argument("--vosk-model", type=str, default="/opt/vosk-model-small-cn-0.15")
    args = ap.parse_args()

    cfg = load_config()
    cfg.storage_dir = os.path.join(HERE, "run50_chat100_data")
    cfg.chroma_dir = os.path.join(HERE, "run50_chroma")
    cfg.max_tokens = 400

    if not cfg.api_key:
        print("未找到 API Key。退出。", flush=True)
        sys.exit(1)

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    key = cfg.api_key
    model = cfg.model

    persona = CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。", schedule=[("8-11", "晨读")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
    core = build_core(cfg, persona)

    client = httpx.Client(timeout=httpx.Timeout(connect=10, read=180, write=15, pool=10))
    total = args.rounds
    voice_total = min(args.voice_rounds, total)

    print(f"开始压测：目标 {total} 轮（其中 {voice_total} 轮语音闭环），"
          f"mode={cfg.mode} 模型={model} RUN_VOICE={RUN_VOICE}", flush=True)

    rounds_log = []
    for i in range(1, total + 1):
        t0 = _now_ms()
        is_voice = (i <= voice_total)  # 前 N 轮做闭环（也可改成指定轮次）
        # 1) 用户侧动态发言
        user_text = user_say(rounds_log, client, url, key, model)

        # 2) 语音闭环：user_text -> TTS -> STT -> 实际送 LLM 的文本
        stt_text = user_text
        audio_in_path = ""
        if is_voice and RUN_VOICE:
            audio_in_path = os.path.join(DATA_DIR, "audio_in", f"r{i:03d}.wav")
            if _gsv_tts(user_text, audio_in_path, args.refer_wav, args.refer_text):
                stt_text = _vosk_recognize(args.vosk_model, audio_in_path)
                with open(os.path.join(DATA_DIR, "stt_raw", f"r{i:03d}.txt"), "w", encoding="utf-8") as f:
                    f.write(stt_text)
            else:
                stt_text = user_text  # TTS 失败降级为原文

        # 3) 梦瑶侧真实回复（带 429 退避重试）；采首字延迟
        llm_t0 = _now_ms()
        first_token_ms = None
        done = None
        assistant_text = ""
        last_err = None
        for attempt in range(6):
            try:
                for ev in core.stream_message(stt_text if is_voice else user_text):
                    if ev["type"] == "body":
                        if first_token_ms is None:
                            first_token_ms = _now_ms() - llm_t0
                        assistant_text += ev["text"]
                    elif ev["type"] == "done":
                        done = ev
                if done is not None:
                    break
            except RuntimeError as exc:
                last_err = exc
                if "429" in str(exc):
                    wait = 10 + attempt * 8
                    print(f"  [梦瑶] 429 退避 {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                raise
            except Exception as exc:
                last_err = exc
                print(f"  [梦瑶] 异常重试: {exc!r}", flush=True)
                time.sleep(5)
                continue
        if done is None:
            assistant_text = assistant_text or "（梦瑶没有回应）"

        llm_total_ms = _now_ms() - llm_t0

        # 4) 记忆检索耗时（包装：再调一次 recall 测耗时，原始已在 done.manifest 里）
        mem_t0 = _now_ms()
        try:
            _ = core.memory_recall(stt_text if is_voice else user_text) if hasattr(core, "memory_recall") else None
        except Exception:
            pass
        mem_ms = _now_ms() - mem_t0

        # 5) 闭环：回答 -> TTS 合成语音（只生成，不打印文本）
        audio_out_path = ""
        if is_voice and RUN_VOICE:
            audio_out_path = os.path.join(DATA_DIR, "audio_out", f"r{i:03d}.wav")
            _gsv_tts(assistant_text, audio_out_path, args.refer_wav, args.refer_text)

        # 6) LLM 原始回答落盘（严格不打印）
        with open(os.path.join(DATA_DIR, "llm_raw", f"r{i:03d}.txt"), "w", encoding="utf-8") as f:
            f.write(assistant_text)

        # 7) 结构化原始记录
        rec = {
            "round": i,
            "mode": "voice" if (is_voice and RUN_VOICE) else "text",
            "user_input": user_text,
            "stt_text": stt_text if is_voice else None,
            "audio_in": audio_in_path or None,
            "audio_out": audio_out_path or None,
            "llm_raw_file": f"llm_raw/r{i:03d}.txt",
            "emotion": done["emotion"] if done else "",
            "affinity_delta": core.last_affinity_delta,
            "affinity_base": core.affinity_base,
            "affinity_dynamics": core.affinity_dynamics,
            "affinity_bond": core.affinity_bond,
            "affinity_stage": core.affinity_stage,
            "manifest": [m["source"] for m in (done["manifest"] if done else [])],
            "assistant_len": len(assistant_text.strip()),
            "latency": {
                "round_total_ms": round(_now_ms() - t0, 1),
                "llm_first_token_ms": round(first_token_ms, 1) if first_token_ms else None,
                "llm_total_ms": round(llm_total_ms, 1),
                "memory_recall_ms": round(mem_ms, 1),
            },
            "ts": time.time(),
        }
        # chat_100.user_say 期望 history 每项含 "user"/"assistant" 键，构造兼容记录
        compat = {
            "round": i,
            "user": user_text,
            "assistant": assistant_text.strip(),
            "emotion": rec["emotion"],
            "affinity_delta": rec["affinity_delta"],
            "affinity_base": rec["affinity_base"],
            "affinity_dynamics": rec["affinity_dynamics"],
            "affinity_bond": rec["affinity_bond"],
            "affinity_stage": rec["affinity_stage"],
            "manifest": rec["manifest"],
            "assistant_len": rec["assistant_len"],
            "ts": rec["ts"],
            "cost_s": rec["latency"]["round_total_ms"] / 1000.0,
            "latency": rec["latency"],
        }
        rounds_log.append(compat)
        with open(OUT_ROUNDS, "w", encoding="utf-8") as f:
            json.dump(rounds_log, f, ensure_ascii=False, indent=1)

        # 仅打印元信息（不打印 LLM 原文）
        print(f"R{i:03d} [{rec['mode']}] Δ={rec['affinity_delta']:+.2f} "
              f"base={rec['affinity_base']:>3} 档={rec['affinity_stage']} "
              f"dyn={rec['affinity_dynamics']:>3} 情绪={rec['emotion']} "
              f"首字={rec['latency']['llm_first_token_ms']}ms "
              f"LLM={rec['latency']['llm_total_ms']}ms "
              f"记忆={rec['latency']['memory_recall_ms']}ms "
              f"总={rec['latency']['round_total_ms']}ms "
              f"用户：{user_text[:24]}", flush=True)
        time.sleep(3)

    client.close()
    print(f"压测完成：共 {len(rounds_log)} 轮，原始数据 -> {DATA_DIR}", flush=True)


if __name__ == "__main__":
    main()
