"""声纹砖运行时集成测试：真实拉起引擎子进程（HTTP），经 client 注册/识别。

验证完整链路：launcher 启动 server_speaker.py → client 调 /enroll /identify /status，
不依赖 palm_sdk（引擎子进程隔离）。
"""
import os
import sys
import time

SPEAKER_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SPEAKER_SRC))

from launcher import discover_venv_python, build_launch_cmd, engine_url, spawn_runtime  # noqa: E402
from client import enroll, identify, fetch_status  # noqa: E402

TEST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
MODEL = os.path.join(SPEAKER_SRC, "speaker_models", "campplus_zh_en_fp16.onnx")
STORE = os.path.join(TEST_DIR, "_integration_store.json")


def main() -> None:
    py = discover_venv_python()
    assert py, "未找到 .venv-speaker"
    # 覆盖 argv：用临时 store，避免污染
    import subprocess

    cmd = [
        py, os.path.join(SPEAKER_SRC, "server_speaker.py"),
        "--port", "19555", "--model", MODEL, "--store", STORE,
        "--sample-rate", "16000", "--threshold", "0.31",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = "http://127.0.0.1:19555"
    try:
        # 等就绪
        for _ in range(30):
            if fetch_status(url) and fetch_status(url).get("ready"):
                break
            time.sleep(1)
        st = fetch_status(url)
        print("引擎状态:", st.get("ready"), "| 模型:", os.path.basename(st.get("model", "")))

        # 注册三个说话人（用各 spkX_1.wav）—— 真实多说话人 1:N 场景
        for spk in ("spkA", "spkB", "spkC"):
            r = enroll(url, spk, os.path.join(TEST_DIR, f"{spk}_1.wav"))
            print("注册", spk, ":", r)

        # 识别同音色不同句（spkA_2）→ 应命中 spkA
        r2 = identify(url, os.path.join(TEST_DIR, "spkA_2.wav"))
        print("识别 spkA_2:", r2, "→ 命中本人" if r2.get("speaker") == "spkA" else "→ 错误")

        # 识别异音色（spkB_3）→ 应命中 spkB（多说话人下不会误判给 spkA）
        r3 = identify(url, os.path.join(TEST_DIR, "spkB_3.wav"))
        print("识别 spkB_3:", r3, "→ 命中本人" if r3.get("speaker") == "spkB" else "→ 错误")

        # 未知说话人（合成白噪声，非语音，从未注册）→ 应判未知
        import numpy as np
        import soundfile as sf

        noise_path = os.path.join(TEST_DIR, "_noise_probe.wav")
        sf.write(noise_path, np.random.randn(16000 * 2).astype(np.float32), 16000)
        r4 = identify(url, noise_path)
        try:
            if os.path.isfile(noise_path):
                os.remove(noise_path)
        except OSError:
            pass
        print("识别未知音(噪声):", r4, "→ 正确判未知" if not r4.get("match") else "→ 误判")
        print("\n集成测试结论：砖完整运行时链路 %s" %
              ("OK" if r2.get("speaker") == "spkA" and r3.get("speaker") == "spkB"
               and not r4.get("match") else "FAIL"))
    finally:
        proc.terminate()
        try:
            if os.path.isfile(STORE):
                os.remove(STORE)
        except OSError:
            pass  # safe-delete 守卫在沙箱内会拦删除，忽略即可（临时文件）


if __name__ == "__main__":
    main()
