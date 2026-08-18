"""声纹引擎服务（独立子进程）：CAM++ 嵌入提取 + 声纹库，经本地 HTTP 暴露。

独立运行于 声纹识别/.venv-speaker（`python server_speaker.py`），绝不 import palm_sdk：
模型路径/采样率/库路径经命令行传入，识别结果进请求响应，主进程经 client 调用。

音频以 base64 wav 字节或原始 int16 PCM（/audio_frame 实时摄入）传入：
- 文件模式（enroll/identify/verify）：POST {wav_b64} 直接提嵌比对。
- 实时模式（audio_frame + flush_identify）：stt 砖把麦克风 PCM 帧扇出到此，
  段结束时 flush_identify 对累计音频做识别，实现「单麦采集、双引擎消费」。
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 直跑脚本模式（launcher 以 `python server_speaker.py` 启动，sys.path[0]=src 目录）：
# 走顶层导入，避免触发 palm_sdk 导入。
try:
    from speaker_core import SpeakerExtractor, SpeakerStore, read_wav
except ImportError:  # 作为独立脚本运行时 src 已在 sys.path[0]
    from speaker_core import SpeakerExtractor, SpeakerStore, read_wav

_LOGGER = logging.getLogger("speaker.engine")


class EngineCore:
    def __init__(self, model_path: str, store_path: str, sample_rate: int,
                 threshold: float) -> None:
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._missing: list[str] = []
        self.extractor: SpeakerExtractor | None = None
        self.store: SpeakerStore | None = None
        try:
            self.extractor = SpeakerExtractor(model_path, num_threads=1)
        except (FileNotFoundError, OSError, ValueError) as exc:
            _LOGGER.warning("声纹模型加载失败: %s", exc)
            self._missing.append(f"model:{exc}")
        try:
            self.store = SpeakerStore(store_path, threshold=threshold)
        except (OSError, ValueError) as exc:
            _LOGGER.warning("声纹库初始化失败: %s", exc)
            self._missing.append(f"store:{exc}")
        # 实时音频缓冲（int16 PCM 字节累积）
        self._frame_buffer = bytearray()
        self._frame_lock = threading.Lock()

    def status(self) -> dict:
        return {
            "ready": self.extractor is not None and self.store is not None,
            "model": self.extractor.model_path if self.extractor else None,
            "sample_rate": self.sample_rate,
            "speakers": self.store.list_speakers() if self.store else [],
            "missing": self._missing,
        }

    def _embedding_from_wav_b64(self, wav_b64: str) -> bytes:
        """wav base64 → 嵌入向量 bytes（numpy tobytes），失败抛错。"""
        if self.extractor is None:
            raise RuntimeError("声纹模型未就绪")
        raw = base64.b64decode(wav_b64)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            emb = self.extractor.compute_from_wav(tmp_path)
        finally:
            os.remove(tmp_path)
        return emb.tobytes()

    def enroll(self, name: str, wav_b64: str) -> dict:
        if self.store is None:
            return {"ok": False, "error": "声纹库未就绪"}
        emb = np_from_bytes(self._embedding_from_wav_b64(wav_b64))
        self.store.enroll(name, emb)
        return {"ok": True, "speaker": name}

    def identify(self, wav_b64: str) -> dict:
        if self.store is None:
            return {"ok": False, "error": "声纹库未就绪"}
        emb = np_from_bytes(self._embedding_from_wav_b64(wav_b64))
        res = self.store.identify(emb)
        return {"ok": True, **res}

    def verify(self, name: str, wav_b64: str) -> dict:
        if self.store is None:
            return {"ok": False, "error": "声纹库未就绪"}
        emb = np_from_bytes(self._embedding_from_wav_b64(wav_b64))
        res = self.store.verify(name, emb)
        return {"ok": True, **res}

    def remove(self, name: str) -> dict:
        if self.store is None:
            return {"ok": False, "error": "声纹库未就绪"}
        return {"ok": self.store.remove(name)}

    def push_frame(self, pcm_b64: str) -> None:
        """实时摄入一段 int16 PCM 帧（stt 扇出的麦克风音频）。"""
        with self._frame_lock:
            self._frame_buffer.extend(base64.b64decode(pcm_b64))

    def flush_identify(self) -> dict:
        """对累计实时音频做识别并清空缓冲。"""
        with self._frame_lock:
            pcm = bytes(self._frame_buffer)
            self._frame_buffer = bytearray()
        if len(pcm) < self.sample_rate * 2:  # 不足 1 秒，跳过
            return {"ok": True, "match": False, "speaker": None, "similarity": 0.0, "short": True}
        import numpy as np
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if self.extractor is None or self.store is None:
            return {"ok": False, "error": "引擎未就绪"}
        emb = self.extractor.compute_embedding(samples, self.sample_rate)
        res = self.store.identify(emb)
        return {"ok": True, **res}


def np_from_bytes(b: bytes) -> "np.ndarray":
    import numpy as np
    return np.frombuffer(b, dtype=np.float32)


def make_handler(engine: EngineCore):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            _LOGGER.debug(fmt, *args)

        def _send_json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/status":
                self._send_json(200, engine.status())
            elif path == "/list":
                self._send_json(200, {"speakers": engine.store.list_speakers() if engine.store else []})
            else:
                self._send_json(404, {"error": f"未知端点 {path}"})

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                if path == "/enroll":
                    p = self._read_json()
                    self._send_json(200, engine.enroll(p.get("name", ""), p.get("wav_b64", "")))
                elif path == "/identify":
                    p = self._read_json()
                    self._send_json(200, engine.identify(p.get("wav_b64", "")))
                elif path == "/verify":
                    p = self._read_json()
                    self._send_json(200, engine.verify(p.get("name", ""), p.get("wav_b64", "")))
                elif path == "/remove":
                    p = self._read_json()
                    self._send_json(200, engine.remove(p.get("name", "")))
                elif path == "/audio_frame":
                    p = self._read_json()
                    engine.push_frame(p.get("pcm_b64", ""))
                    self._send_json(200, {"ok": True})
                elif path == "/flush_identify":
                    self._send_json(200, engine.flush_identify())
                else:
                    self._send_json(404, {"error": f"未知端点 {path}"})
            except (KeyError, ValueError, RuntimeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

        def do_DELETE(self):
            # 兼容 /control?command=exit 的退出方式
            path = self.path.split("?")[0]
            if path == "/control" and "command=exit" in self.path:
                self._send_json(200, {"ok": True})
                threading.Thread(target=engine_shutdown).start()
            else:
                self._send_json(404, {"error": "未知端点"})

    return Handler


_engine_server = None


def engine_shutdown() -> None:
    time.sleep(0.2)
    if _engine_server is not None:
        _engine_server.shutdown()


def main() -> None:
    global _engine_server
    parser = argparse.ArgumentParser(description="P.A.L.M 声纹引擎（独立子进程）")
    parser.add_argument("--port", type=int, default=19510)
    parser.add_argument("--model", default="")
    parser.add_argument("--store", default="")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--threshold", type=float, default=0.31)
    args = parser.parse_args()
    engine = EngineCore(args.model, args.store, args.sample_rate, args.threshold)
    _LOGGER.info("声纹引擎就绪（model=%s ready=%s 声纹数=%d）",
                 args.model, engine.status()["ready"], len(engine.status()["speakers"]))
    _engine_server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    _engine_server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    main()
