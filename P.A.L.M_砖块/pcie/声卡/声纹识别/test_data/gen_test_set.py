"""用 CosyVoice 砖（已装 venv）生成声纹检验集：3 个克隆音色 × 4 句不同文本。

每个说话人用一段不同的真人参考音频做 zero_shot 克隆，合成不同文案，
用于验证声纹砖「同音色跨文本应判同、异音色应判异」的分离度。

输出到本目录 {spkX}_{i}.wav（CosyVoice 经 COSY_OUTPUT_DIR 直写）。
"""
import os
import sys

COSY_DIR = r"C:\Users\24459\Desktop\P.A.L.M\语音合成 (CosyVoice)"
OUT_DIR = r"C:\Users\24459\Desktop\P.A.L.M\声纹识别\test_data"
os.environ["COSY_OUTPUT_DIR"] = OUT_DIR
sys.path.insert(0, COSY_DIR)

import src.engine as engine  # noqa: E402

# (参考音频, 参考原文) —— 三个不同真人音色
REFS = {
    "spkA": (r"C:\Users\24459\Desktop\P.A.L.M\Data\CosyVoice_src\asset\zero_shot_prompt.wav",
             "今天天气真好，我们出去散步吧。"),
    "spkB": (r"C:\Users\24459\Desktop\P.A.L.M\语音合成 (GPT-SoVITS)\src\gpt_sovits\ref_audio.wav",
             "这是一个参考音频，用于语音合成测试。"),
    "spkC": (r"C:\Users\24459\Desktop\P.A.L.M\Data\CosyVoice_src\asset\cross_lingual_prompt.wav",
             "大家好，我是跨语言语音合成的示例。"),
}

# 4 句不同文案（三个说话人共用，验证跨文本稳定性）
TEXTS = [
    "你好，我是你的智能语音助手，很高兴为你服务。",
    "今天的会议改到下午三点，请准时参加。",
    "明天可能会下雨，记得带伞出门。",
    "请把这份文件发送到我的邮箱，谢谢。",
]


def main() -> None:
    for spk, (ref, ref_text) in REFS.items():
        for i, text in enumerate(TEXTS, 1):
            vid = f"{spk}_{i}"
            meta = engine.create_voice(
                seed_audio=ref, seed_text=ref_text, sample_text=text, voice_id=vid
            )
            print(f"[ok] {vid} -> {meta['wav_path']}", flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
