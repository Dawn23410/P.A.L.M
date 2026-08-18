"""STT 引擎服务（独立子进程）：麦克风采集 + VAD + KWS + 流式 ASR + 事件队列。

独立运行于 bricks/stt/.venv-stt（`python -m app.bricks.stt.engine.server`），不依赖主进程
任何模块：模型路径/采样率经命令行传入，识别事件（vad_state / partial /
transcript）进带序号队列，主进程轮询 /events?after= 增量拉取。

模型缺失不崩溃：/status 报告缺失项（优雅降级），/start 返回可辨识错误。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import sounddevice as sd

# 直跑脚本模式（launcher 以 `python <server.py>` 启动，sys.path[0]=engine 目录）：
# 走顶层导入，避免触发 app.bricks.__init__（其会导入全部砖块，依赖主 venv）。
try:
    from .asr import StreamingAsr
    from .kws import KeywordSpotter, sanitize_keywords
    from .vad import VadDetector
except ImportError:  # 作为独立脚本运行时 engine 目录已在 sys.path[0]
    from asr import StreamingAsr
    from kws import KeywordSpotter, sanitize_keywords
    from vad import VadDetector

_LOGGER = logging.getLogger("stt.engine")
_PARTIAL_INTERVAL = 0.2  # 中间结果节流：同文本 200ms 内不重复发


class EventQueue:
    """带序号的事件队列：主进程按 after=seq 增量拉取，防漏事件。"""

    def __init__(self, maxlen: int = 2000) -> None:
        self._items: deque = deque(maxlen=maxlen)
        self._seq = 0
        self._lock = threading.Lock()

    def push(self, event_type: str, payload: dict) -> None:
        with self._lock:
            self._seq += 1
            self._items.append({"seq": self._seq, "type": event_type, "payload": payload})

    def fetch_after(self, after: int) -> list[dict]:
        with self._lock:
            return [item for item in self._items if item["seq"] > after]


class EngineCore:
    def __init__(self, sample_rate: int, vad_path: str, asr_dir: str,
                 kws_dir: str, keywords_file: str) -> None:
        self.sample_rate = sample_rate
        self.events = EventQueue()
        self._audio_queue: queue.Queue = queue.Queue(maxsize=256)
        self._listening = False
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._vad: VadDetector | None = None
        self._asr: StreamingAsr | None = None
        self._kws: KeywordSpotter | None = None
        self._missing: list[str] = []
        self._input_stream = None
        self._pending: dict[int, dict] = {}
        self._fallback_stream = None  # 无 VAD 时持续累积的兜底 ASR 流
        self._prev_speaking = False
        self._load_models(vad_path, asr_dir, kws_dir, keywords_file)

    def _load_models(self, vad_path: str, asr_dir: str,
                     kws_dir: str, keywords_file: str) -> None:
        if asr_dir and StreamingAsr.is_ready(asr_dir):
            try:
                self._asr = StreamingAsr(asr_dir, self.sample_rate)
            except (OSError, ValueError) as exc:
                _LOGGER.warning("ASR 加载失败: %s", exc)
                self._missing.append(f"asr:{exc}")
        else:
            self._missing.append("asr")
        if vad_path:
            try:
                self._vad = VadDetector(vad_path, self.sample_rate)
            except (OSError, ValueError, RuntimeError) as exc:  # RuntimeError=模型加载失败
                _LOGGER.warning("VAD 加载失败: %s", exc)
                self._missing.append(f"vad:{exc}")
        else:
            self._missing.append("vad")
        if kws_dir and keywords_file and os.path.isfile(keywords_file):
            try:
                self._kws = self._build_spotter(kws_dir, keywords_file)
            except (OSError, ValueError, RuntimeError) as exc:
                _LOGGER.warning("KWS 加载失败: %s", exc)
                self._missing.append(f"kws:{exc}")
        else:
            self._missing.append("kws")

    def _build_spotter(self, kws_dir: str, keywords_file: str) -> KeywordSpotter:
        """预检关键词音素后构造 KWS；坏行剔除写回，全坏则降级为不可用。"""
        with open(keywords_file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        valid, dropped = sanitize_keywords(os.path.join(kws_dir, "tokens.txt"), lines)
        if dropped:
            _LOGGER.warning("KWS 剔除 %d 条音素不匹配的关键词: %s", len(dropped), dropped[:3])
            with open(keywords_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(valid) + ("\n" if valid else ""))
        if not valid:
            raise RuntimeError("关键词文件与模型音素不匹配（无可用关键词）")
        return KeywordSpotter(kws_dir, keywords_file)

    def status(self) -> dict:
        return {
            "listening": self._listening,
            "models": {
                "vad": self._vad is not None,
                "asr": self._asr is not None,
                "kws": self._kws is not None,
            },
            "missing": self._missing,
            "sample_rate": self.sample_rate,
        }

    def start_listening(self) -> tuple[bool, str]:
        if self._vad is None and self._asr is None:
            return False, "无可用的识别模型（VAD/ASR 均未就绪）"
        with self._state_lock:
            if self._listening:
                return True, "already_listening"
            try:
                self._input_stream = sd.InputStream(
                    samplerate=self.sample_rate, channels=1, dtype="int16",
                    blocksize=0, callback=self._audio_callback,
                )
                self._input_stream.start()
            except Exception as exc:  # noqa: BLE001  PortAudio 设备异常类型不统一
                return False, f"麦克风启动失败: {exc}"
            self._listening = True
        _LOGGER.info("开始监听麦克风")
        return True, ""

    def stop_listening(self) -> None:
        with self._state_lock:
            self._listening = False
            if self._input_stream is not None:
                try:
                    self._input_stream.stop()
                    self._input_stream.close()
                except Exception:  # noqa: BLE001
                    pass
                self._input_stream = None
        # 把残余语音收尾成一条完整结果（flush 让 VAD 结束当前段）。
        if self._vad is not None:
            self._vad.flush()
        _LOGGER.info("停止监听")

    def reload_keywords(self, keywords_file: str, lines: list[str]) -> tuple[bool, str]:
        """更新关键词文件并重建 KWS；坏词剔除，KWS 未就绪时仅写文件。"""
        if self._kws is not None:
            kws_dir = os.path.dirname(keywords_file)
            valid, dropped = sanitize_keywords(os.path.join(kws_dir, "tokens.txt"), lines)
            lines = valid
            if dropped:
                return False, f"已剔除 {len(dropped)} 条音素不匹配的关键词: {dropped[:3]}"
        try:
            os.makedirs(os.path.dirname(keywords_file), exist_ok=True)
            with open(keywords_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
        except OSError as exc:
            return False, f"写入关键词文件失败: {exc}"
        if self._kws is None:
            return True, "关键词已保存（KWS 未启用，待模型就绪后生效）"
        kws_dir = os.path.dirname(keywords_file)
        try:
            self._kws = KeywordSpotter(kws_dir, keywords_file)
        except (OSError, ValueError, RuntimeError) as exc:
            return False, f"KWS 重建失败: {exc}"
        return True, "关键词已更新"

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if self._listening:
            try:
                self._audio_queue.put_nowait(indata.flatten().copy())
            except queue.Full:
                pass

    def _process_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                samples = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                samples = None
            if samples is not None:
                if self._vad is not None:
                    self._vad.accept_waveform(samples)
                elif self._asr is not None:
                    self._feed_fallback(samples)
            if self._vad is not None:
                # 每轮都 drain：实时模式下队列永不为空，段处理不能等 while 退出。
                self._drain_vad_segments()
                self._emit_vad_state(self._vad.has_segment())
        # 退出收尾：stop 时 VAD 已 flush，把残余段处理完。
        if self._vad is not None:
            self._drain_vad_segments()
        elif self._asr is not None and self._fallback_stream is not None:
            self._asr.flush_stream(self._fallback_stream)  # 收尾残余波形再取结果
            text = self._asr.partial(self._fallback_stream)
            if text:
                self.events.push("transcript", {"text": text, "is_final": True, "keyword": ""})

    def _feed_fallback(self, samples: np.ndarray) -> None:
        # 采样累积由 StreamingAsr.feed 内部完成，此处直接喂入即可。
        if self._fallback_stream is None:
            self._fallback_stream = self._asr.create_stream()
        self._asr.feed(self._fallback_stream, samples)

    def _drain_vad_segments(self) -> None:
        vad = self._vad
        while vad.has_segment():
            segment = vad.front
            key = id(segment)
            info = self._pending.get(key)
            if info is None:
                info = {
                    "asr": self._asr.create_stream() if self._asr else None,
                    "kws": self._kws.create_stream() if self._kws else None,
                    "fed": 0, "last_partial": "", "last_ts": 0.0,
                }
                self._pending[key] = info
            samples = np.asarray(segment.samples)
            new = samples[info["fed"]:]
            info["fed"] = len(samples)
            if len(new) > 0:
                if info["asr"] is not None:
                    self._asr.feed(info["asr"], new)
                if info["kws"] is not None:
                    self._kws.feed(info["kws"], new)
                self._emit_partial(info)
            self._vad.pop()
            if info["asr"] is not None:
                self._asr.flush_stream(info["asr"])  # 段结束，喂完不足一块的尾部
            self._emit_transcript(info)
            del self._pending[key]

    def _emit_partial(self, info: dict) -> None:
        if info["asr"] is None:
            return
        text = self._asr.partial(info["asr"])
        now = time.monotonic()
        if text and text != info["last_partial"] and now - info["last_ts"] >= _PARTIAL_INTERVAL:
            info["last_partial"] = text
            info["last_ts"] = now
            self.events.push("partial", {"text": text})

    def _emit_transcript(self, info: dict) -> None:
        text = ""
        keyword = ""
        if info["asr"] is not None:
            text = self._asr.partial(info["asr"])
        if info["kws"] is not None:
            keyword = self._kws.hit_keyword(info["kws"])
        if text:
            self.events.push("transcript", {"text": text, "is_final": True, "keyword": keyword})

    def _emit_vad_state(self, speaking: bool) -> None:
        if speaking != self._prev_speaking:
            self._prev_speaking = speaking
            self.events.push("vad_state", {"state": "speaking" if speaking else "silence"})

    def run(self) -> None:
        threading.Thread(target=self._process_loop, daemon=True).start()
        _LOGGER.info("STT 引擎就绪（vad=%s asr=%s kws=%s）",
                     self._vad is not None, self._asr is not None, self._kws is not None)


import os  # noqa: E402  reload_keywords 需要，置于模块末尾避免打乱顶部导入组


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

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/status":
                self._send_json(200, engine.status())
            elif path == "/events":
                after = int(self.path.split("after=")[-1] or 0) if "after=" in self.path else 0
                self._send_json(200, {"events": engine.events.fetch_after(after)})
            else:
                self._send_json(404, {"error": f"未知端点 {path}"})

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/start":
                ok, msg = engine.start_listening()
                self._send_json(200 if ok else 409, {"ok": ok, "message": msg})
            elif path == "/stop":
                engine.stop_listening()
                self._send_json(200, {"ok": True})
            elif path == "/control":
                command = self.path.split("command=")[-1] if "command=" in self.path else ""
                if command == "exit":
                    self._send_json(200, {"ok": True})
                    threading.Thread(target=engine_shutdown).start()
                else:
                    self._send_json(400, {"error": "未知控制命令"})
            else:
                self._send_json(404, {"error": f"未知端点 {path}"})

        def do_PUT(self):
            if self.path.split("?")[0] != "/keywords":
                self._send_json(404, {"error": "未知端点"})
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                lines = [str(item).strip() for item in payload.get("keywords", [])]
            except (ValueError, AttributeError):
                self._send_json(400, {"error": "请求体需为 JSON 且含 keywords 数组"})
                return
            ok, msg = engine.reload_keywords(engine_keywords_file, lines)
            self._send_json(200 if ok else 500, {"ok": ok, "message": msg})

    return Handler


engine_keywords_file = ""
_engine_server = None


def engine_shutdown() -> None:
    time.sleep(0.2)
    if _engine_server is not None:
        _engine_server.shutdown()


def main() -> None:
    global engine_keywords_file, _engine_server
    parser = argparse.ArgumentParser(description="P.A.L.M STT 引擎（独立子进程）")
    parser.add_argument("--port", type=int, default=19500)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--vad", default="")
    parser.add_argument("--asr-dir", default="")
    parser.add_argument("--kws-dir", default="")
    parser.add_argument("--kws-keywords", default="")
    args = parser.parse_args()
    engine_keywords_file = args.kws_keywords
    engine = EngineCore(args.sample_rate, args.vad, args.asr_dir,
                        args.kws_dir, args.kws_keywords)
    engine.run()
    _engine_server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    _LOGGER.info("HTTP 服务监听 127.0.0.1:%s", args.port)
    _engine_server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    main()
