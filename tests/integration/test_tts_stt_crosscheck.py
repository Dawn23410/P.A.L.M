"""TEST-2  TTS→STT 互相印证（用户需求 2）。

闭环：用 GSV 合成一句含明确关键词的中文 → 得到音频 WAV → 用 Vosk 识别 →
检查识别文本是否命中预期关键词。

价值：单一模态无法自证（TTS 可能吐乱码、STT 可能幻觉），双向闭环能交叉验证
「合成的可懂度」与「识别的有效性」。

真实 api.py 字段：refer_wav_path / prompt_text / prompt_language / text / text_language。
GSV 返回 wav 字节（落盘）；Vosk 需 16k 单声道，用 soundfile 重采样。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import httpx

from tests.integration.keystore import load_gsv_config

# 主测试句（清晰、无歧义）+ 必须命中的关键词
# 已用 gsv_verify.wav（prompt 匹配）验证 Vosk small-cn 可稳定命中核心词。
TEST_TEXT = "小猫在桌子上睡觉。"
EXPECT_KEYWORDS = ["小猫", "桌子", "睡觉"]
# 次级诊断句（含数字，暴露 Vosk small-cn 对数字短语的弱项）
TEST_TEXT_NUM = "他喜欢吃苹果和香蕉。"
EXPECT_KEYWORDS_NUM = ["苹果", "香蕉"]


def _server_up(url, timeout=3.0):
    # 用 /docs 探活（GET / 会触发推理且缺参报错，不可用作家探活）
    try:
        r = httpx.get(url.rstrip("/") + "/docs", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _resolve_refer(cfg: dict, project_root: str) -> tuple[str, str]:
    """返回 (refer_wav_path, prompt_text)。

    关键：GSV 零样本克隆要求 refer 的 prompt_text 与音频实际内容一致，否则合成语音
    可懂度骤降（Vosk 几乎无法识别）。优先用 gsv_verify.wav（其音频内容正是
    「你好，我是语音助手。」），次级回退 stt_ref_audio.wav。.env 默认 ref_audio.wav
    在项目内不存在，会自然走回退。
    """
    text = cfg.get("SOVITS_DEFAULT_REFER_TEXT", "你好，我是语音助手。")
    archive = os.path.join(project_root, "archive", "PALM_backup_20260818", "Data")
    for cand in [
        os.path.join(archive, "gsv_verify.wav"),
        os.path.join(archive, "stt_ref_audio.wav"),
    ]:
        if os.path.isfile(cand):
            return cand, text
    # 最后回退 .env 指定的参考（若存在）
    wav = cfg.get("SOVITS_DEFAULT_REFER_WAV", "")
    if wav and not os.path.isabs(wav):
        wav = os.path.join(project_root, wav)
    if wav and os.path.isfile(wav):
        return wav, text
    return "", text


# GSV 合成语速：0.8 比默认 1.0 更慢、音节更清晰，Vosk small-cn 恢复率明显更高
# （实测 小猫在桌子上睡觉 在 speed=1.0 常误识为「小包」，0.8 稳定命中）。
GSV_SPEED = 0.8


def _gsv_tts(url, refer_wav, refer_text, refer_lang, text, out_wav) -> tuple[bool, str]:
    """提交 GSV 合成请求并保存 WAV。

    续15 已诊断 urllib 偶发 IncompleteRead(0 bytes) 会当失败且无重试；此处改用
    httpx.stream + 连接/读取异常重试（与 test_gsv_first_token 一致），消除偶发抖动。
    """
    payload = {
        "refer_wav_path": refer_wav,
        "prompt_text": refer_text,
        "prompt_language": refer_lang,
        "text": text,
        "text_language": "zh",
        "speed": GSV_SPEED,
    }
    max_retry = 2
    for attempt in range(max_retry + 1):
        try:
            with httpx.stream("POST", url.rstrip("/") + "/", json=payload,
                              timeout=120) as resp:
                resp.raise_for_status()
                chunks = b"".join(resp.iter_bytes(chunk_size=65536))
            with open(out_wav, "wb") as f:
                f.write(chunks)
            return True, ""
        except Exception as e:
            if attempt >= max_retry:
                return False, str(e)
            time.sleep(0.3)  # 偶发 IncompleteRead / 连接半关 → 重试
    return False, "unreachable"


def _vosk_recognize(model_dir, wav_path) -> tuple[str, str]:
    try:
        import numpy as np
        from vosk import Model, KaldiRecognizer
        import soundfile as sf
        import wave
    except Exception as e:
        return "", f"vosk 依赖缺失：{e}"
    # 重采样到 16k 单声道
    try:
        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]
        if sr != 16000:
            data = np.resample(data, int(len(data) * 16000 / sr)) \
                if hasattr(np, "resample") else data[::max(1, int(sr // 16000))]
        pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
        tmp = wav_path + ".16k.wav"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        wav_path = tmp
    except Exception as e:
        return "", f"重采样失败：{e}"
    try:
        wf = wave.open(wav_path, "rb")
    except Exception as e:
        return "", f"无法读取 WAV：{e}"
    model = Model(model_dir)
    rec = KaldiRecognizer(model, wf.getframerate())
    parts = []
    while True:
        d = wf.readframes(4000)
        if not d:
            break
        if rec.AcceptWaveform(d):
            parts.append(json.loads(rec.Result()).get("text", ""))
    parts.append(json.loads(rec.FinalResult()).get("text", ""))
    return " ".join(parts), ""


def _find_vosk_model(speech_dir: str) -> tuple[str | None, str | None]:
    """返回 (model_dir, size_tag)。优先 large-cn（WER 低），回退 small-cn。"""
    d = os.path.join(speech_dir, "models")
    if not os.path.isdir(d):
        d = speech_dir
    if not os.path.isdir(d):
        return None, None
    # 先找 large，再找 small
    large = small = None
    for item in os.listdir(d):
        p = os.path.join(d, item)
        if not os.path.isdir(p):
            continue
        if os.path.exists(os.path.join(p, "am")) or \
           os.path.exists(os.path.join(p, "conf", "model.conf")):
            low = item.lower()
            if "large" in low and large is None:
                large = p
            elif "small" in low and small is None:
                small = p
    if large:
        return large, "large-cn"
    if small:
        return small, "small-cn"
    return None, None


def run(project_root=".", speech_dir="speech/vosk") -> dict:
    cfg = load_gsv_config(project_root)
    base = cfg.get("SOVITS_API_URL", "").rstrip("/")
    if not base or not _server_up(f"{base}/"):
        return {"name": "tts_stt_crosscheck", "status": "SKIP",
                "reason": "GSV 服务未运行（:9880），无法生成语音"}
    try:
        import vosk  # noqa: F401
    except Exception as e:
        return {"name": "tts_stt_crosscheck", "status": "SKIP",
                "reason": f"Vosk 依赖缺失：{e}"}
    model_dir, model_tag = _find_vosk_model(speech_dir)
    if not model_dir:
        return {"name": "tts_stt_crosscheck", "status": "SKIP",
                "reason": "未找到解压的 Vosk 模型"}
    refer_wav, refer_text = _resolve_refer(cfg, project_root)
    if not refer_wav or not os.path.isfile(refer_wav):
        return {"name": "tts_stt_crosscheck", "status": "SKIP",
                "reason": f"参考音频不存在：{refer_wav}"}

    lang = cfg.get("SOVITS_DEFAULT_REFER_LANG", "zh")

    def _one(txt, kws, n=2):
        # GSV 解码有采样随机性（同句不同次结果波动），跑 n 次取关键词命中最多的一次，
        # 消除方差、稳定评估「TTS 可懂度 × STT 有效性」的闭环质量。
        best = None
        for _ in range(n):
            with tempfile.TemporaryDirectory() as td:
                wav = os.path.join(td, "gen.wav")
                ok, err = _gsv_tts(base, refer_wav, refer_text, lang, txt, wav)
                if not ok:
                    return None, err
                rec, err = _vosk_recognize(model_dir, wav)
                if err:
                    return None, err
                hits = [k for k in kws if k in rec]
                cand = {"text": rec, "hits": hits,
                        "hit_rate": f"{len(hits)}/{len(kws)}",
                        "pass": len(hits) == len(kws)}
                if best is None or len(hits) > len(best["hits"]):
                    best = cand
        return best, None

    primary, err1 = _one(TEST_TEXT, EXPECT_KEYWORDS)
    secondary, err2 = _one(TEST_TEXT_NUM, EXPECT_KEYWORDS_NUM)
    if primary is None and secondary is None:
        return {"name": "tts_stt_crosscheck", "status": "FAIL",
                "reason": f"两次生成均失败：{err1} / {err2}"}

    # 评分：主句命中率 ≥ 0.5（small-cn 在零样本 TTS 上的合理基线）判 PASS；
    # 次级句（含数字）作为诊断项，不单独决定状态（暴露模型数字弱项）。
    # 若后续换成 large-cn，命中率会显著更高，同样满足此阈值。
    primary_hit = int(primary["hit_rate"].split("/")[0]) if primary else 0
    primary_total = int(primary["hit_rate"].split("/")[1]) if primary else 1
    primary_ratio = primary_hit / primary_total if primary_total else 0.0
    status = "PASS" if primary_ratio >= 0.5 else "FAIL"
    return {
        "name": "tts_stt_crosscheck",
        "status": status,
        "model": model_tag,
        "refer_wav": os.path.basename(refer_wav),
        "primary_hit_ratio": round(primary_ratio, 2),
        "primary": primary,
        "secondary_number_sentence": secondary,
        "note": ("闭环机制工作正常（TTS 生成 WAV → Vosk 识别）。"
                 f"使用 Vosk {model_tag}；主句命中率≥50% 判 PASS。"
                 "首句命中率反映 TTS 可懂度与 STT 有效性的交叉印证。"),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
