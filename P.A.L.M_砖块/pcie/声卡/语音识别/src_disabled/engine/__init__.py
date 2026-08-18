"""STT 引擎子进程包（独立运行于 bricks/stt/.venv-stt，不依赖主进程任何模块）。

被 `python -m app.bricks.stt.engine.server` 拉起，麦克风采集 + VAD + KWS + 流式 ASR
都在本进程内完成，主进程经 HTTP 轮询事件队列拿到识别结果，实现推理隔离。
"""
