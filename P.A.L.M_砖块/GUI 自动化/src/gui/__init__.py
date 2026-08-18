"""GUI 自动化工具组（AI 工具，非砖块）。

系统级键鼠 + 截图 OCR 定位 + 开关识别。「机器眼 + 机器手指」能力集合。

整合说明（2026-08-14）：GUI 自动化对外统一入口是 automation 砖的 `automate` 工具，
本模块不再维护「四组工具聚合列表」（GUI_TOOL_GROUPS）——该机制原本打算把精细工具注册进
全局工具表，但实际从未被消费，且 automation 砖已用 `execute_gui_intent` 闭环覆盖其能力，
故移除，避免误导后续维护以为存在另一套 GUI 工具注册。

本模块仅保留 `assistive_mode` 的导入副作用（必须在 uiautomation 之前声明 COM 辅助技术客户端）。
各精细 Tool 类（如 atlas_tool 内查询类、executor/tool 的 RunAutomationTool 等）仍是普通模块级
定义，可作为潜在能力按需被 automation 砖内部调用，但不经此模块聚合注册。
"""
from __future__ import annotations

# 必须在 uia_operate 等导入 uiautomation 之前声明 COM 辅助技术客户端（见 assistive_mode）
from . import assistive_mode  # noqa: F401

__all__ = ["assistive_mode"]
