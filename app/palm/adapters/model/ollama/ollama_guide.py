"""薄桥接层：实现已迁至独立项目「Ollama嵌入」（`palm_ollama.workspace`）。

原模块路径与导出保留，调用面不变；本项目 2026-09-10 起不再自持该实现。
"""
import palm_boot  # noqa: F401,E402  自举：挂载 Ollama嵌入 等独立项目

from palm_ollama.workspace.ollama_guide import *  # noqa: F401,F403,E402
