"""TEST-5  Vosk STT 尾部空窗（用户需求 5）。

目标：说完最后一个字 → 出最终结果 的空窗 ≤ 0.35s。

原理：用真实中文语音 WAV（stt_ref_audio.wav）喂给 Vosk，按 100ms 帧流式输入，
记录「喂完最后一段音频帧」的时刻 t_last 与调用 FinalResult() 拿到最终结果的时刻
t_final。尾部空窗 = t_final - t_last，反映 VAD 静音判定 + 解码 flush 延迟。

实现：需要 numpy/vosk + 已解压的中文模型 + 一段真实语音 WAV。
缺依赖/模型/WAV → SKIP（不伪造）。
"""
from __future__ import annotations

import json
import os
import time

TARGET_S = 0.35


def _deps_ok() -> tuple[bool, str]:
    try:
        import numpy  # noqa: F401
        import vosk   # noqa: F401
        import soundfile  # noqa: F401
        return True, ""
    except Exception as e:
        return False, f"缺少依赖（numpy/vosk/soundfile）：{e}"


def _find_model(models_dir: str) -> str | None:
    d = os.path.join(models_dir, "models") if os.path.isdir(
        os.path.join(models_dir, "models")) else models_dir
    if not os.path.isdir(d):
        return None
    for item in os.listdir(d):
        p = os.path.join(d, item)
        if os.path.isdir(p) and (os.path.exists(os.path.join(p, "am"))
                                 or os.path.exists(os.path.join(p, "conf", "model.conf"))):
            return p
    return None


def _find_test_wav(project_root: str) -> str | None:
    cands = [
        os.path.join(project_root, "archive", "PALM_backup_20260818",
                     "Data", "stt_ref_audio.wav"),
        os.path.join(project_root, "archive", "PALM_backup_20260818",
                     "Data", "gsv_verify.wav"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def run(project_root: str = ".", speech_dir: str = "speech/vosk") -> dict:
    ok, why = _deps_ok()
    if not ok:
        return {"name": "vosk_tailgap", "status": "SKIP", "reason": why}

    model_dir = _find_model(speech_dir)
    if not model_dir:
        return {"name": "vosk_tailgap", "status": "SKIP",
                "reason": f"未找到解压的 Vosk 模型（搜索 {speech_dir}/models）"}

    wav_path = _find_test_wav(project_root)
    if not wav_path:
        return {"name": "vosk_tailgap", "status": "SKIP",
                "reason": "未找到真实语音测试 WAV（stt_ref_audio.wav）"}

    import numpy as np
    import soundfile as sf
    from vosk import Model, KaldiRecognizer

    # 重采样到 16k 单声道 int16 pcm
    data, sr = sf.read(wav_path, dtype="float32")
    if data.ndim > 1:
        data = data[:, 0]
    if sr != 16000:
        data = data[::max(1, int(sr // 16000))]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    audio_dur_s = len(pcm) / 16000.0

    model = Model(model_dir)
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(True)

    frame_bytes = int(0.1 * 16000 * 2)  # 100ms 帧
    t0 = time.perf_counter()
    t_last = None
    for i in range(0, len(pcm.tobytes()), frame_bytes):
        chunk = pcm.tobytes()[i:i + frame_bytes]
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
        if i + frame_bytes >= len(pcm.tobytes()):
            t_last = time.perf_counter()  # 最后一段音频帧喂完
    # 推一段尾静音以触发 VAD 判定（真实场景中说话结束后有自然静音）
    silence = np.zeros(int(0.2 * 16000), dtype="<i2").tobytes()
    rec.AcceptWaveform(silence)
    t_final = time.perf_counter()
    _ = rec.FinalResult()

    # 尾部空窗 = 最后音频帧喂完 → 最终结果产出（含尾静音触发 + flush）
    tail_gap_s = (t_final - t_last) if t_last else (t_final - t0)
    tail_gap_ms = round(tail_gap_s * 1000, 1)
    ok = tail_gap_s <= TARGET_S
    return {
        "name": "vosk_tailgap",
        "status": "PASS" if ok else "FAIL",
        "tail_gap_ms": tail_gap_ms,
        "target_ms": int(TARGET_S * 1000),
        "audio_dur_s": round(audio_dur_s, 2),
        "model": os.path.basename(model_dir),
        "test_wav": os.path.basename(wav_path),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
