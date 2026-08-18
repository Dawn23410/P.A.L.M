"""【状态：已封砖 2026-08-14】自动化砖块：对外单一入口 `automate`，对内聚合 GUI 工具组。

设计意图（呼应 2026-08-13 重构与后续讨论）：
- 仅暴露一个工具 `automate` 给 agent/用户表达「目的」；DESKTOP/ATLAS/EXECUTOR/UIA
  四组精细工具不注册为 agent 工具，只作为引擎内部能力被推理器与执行器调用。
- llm_enhance 走用户设置（settings.json 的 gui_llm_enhance），工具签名不接收该参数，
  杜绝 LLM 调用路径自行开启大模型；默认关闭=纯逻辑推理，LLM 仅在开启且逻辑失败时兜底。
- 引擎核心复用 automation_orchestrator.execute_gui_intent 的「推理→执行→回写」闭环。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared.tooling import Tool, ToolSpec, get_registry

from .gui.automation_orchestrator import execute_gui_intent
from .gui.gui_settings import is_llm_enhance_enabled
from .gui.perceive import (
    perceive_desktop,
    select_target_window,
    ensure_foreground,
)
from .gui import (
    click_collector,
    atlas_calibration,
    reverse_builder,
    background_scan,
)

_LOGGER = logging.getLogger(__name__)

# 规划器系统提示：约束步骤 schema，使 LLM 产出可被执行器直接消费的 JSON 数组。
_PLANNER_SYSTEM = (
    "你是 GUI 自动化规划器。根据界面上下文与用户意图，产出可在目标窗口执行的步骤数组。"
    "每个步骤是 JSON 对象，必须含 action 字段，取值之一："
    "click（点击控件，需 name/automation_id/control_type 之一定位）、"
    "type（输入文本，需 text）、press（按键，需 key）、hotkey（组合键，需 keys）、"
    "wait（等待秒数，需 timeout）、check（读取开关状态，需 automation_id）、"
    "verify（校验控件存在，需 expect）、close（关闭窗口）。"
    "只输出 JSON 数组，不要 Markdown 代码块或解释。"
)


def _parse_steps(text: str) -> list[dict] | None:
    """从 LLM 文本中解析 JSON 步骤数组；容忍 ```json 包裹与前后杂文。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # 去代码围栏：取首个 ``` 与下一个 ``` 之间的内容
        parts = s.split("```", 2)
        s = parts[1] if len(parts) > 1 else s
        if s.lower().startswith("json"):
            s = s[4:]
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        arr = json.loads(s[start:end + 1])
    except (ValueError, json.JSONDecodeError):
        return None
    if isinstance(arr, list) and all(isinstance(x, dict) for x in arr):
        return arr
    return None


async def _build_llm_planner() -> Callable | None:
    """仅在 llm_enhance 开启时构造 LLM 兜底规划器；否则返回 None（抑制 LLM）。

    复用对话同款模型供应商（agent_provider 上下文变量）+ stream_llm 桥，
    不要求调用方透传模型参数；聊天模型即可承担文本兜底（无需视觉能力）。
    """
    if not is_llm_enhance_enabled():
        return None
    try:
        from palm_sdk.bricks.agent.llm_bridge import stream_llm
        from palm_sdk.bricks._shared.tooling import agent_model, agent_provider
    except Exception as exc:
        _LOGGER.warning("LLM 规划器依赖不可用，降级为无 LLM: %s", exc)
        return None

    provider = agent_provider.get()
    model = agent_model.get() or ""
    if not model:
        _LOGGER.warning("无可用对话模型，LLM 规划器不可用")
        return None

    async def planner(software_id: str, intent: str, context: dict) -> list[dict] | None:
        ctx_text = json.dumps(context, ensure_ascii=False)[:8000] if context else "（无上下文）"
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": (
                f"软件：{software_id}\n用户意图：{intent}\n"
                f"当前界面上下文（UIA 树/地图）：\n{ctx_text}\n\n"
                "请仅输出 JSON 步骤数组，不要任何解释。"
            )},
        ]
        collected = ""
        try:
            async for chunk in stream_llm(messages, model=model, provider=provider):
                content = chunk.get("content") or ""
                if content:
                    collected += content
        except Exception as exc:
            _LOGGER.warning("LLM 规划调用失败: %s", exc)
            return None
        return _parse_steps(collected)

    return planner


def _format_result(result: dict) -> str:
    """把闭环结果压成给用户的简短文本（不泄漏底层细节，保留关键状态）。"""
    source = result.get("source")
    trust = result.get("trust")
    needs_llm = result.get("needs_llm")
    exec_ok = result.get("exec_success")
    llm_used = result.get("llm_used")
    note = result.get("note") or ""
    desktop = result.get("desktop") or {}
    lines: list[str] = []
    if desktop:
        lines.append(
            f"桌面：可见窗口 {desktop.get('window_count', '?')} 个，"
            f"目标窗聚焦={'是' if desktop.get('focused') else '否'}"
        )
    if source:
        lines.append(f"推理来源：{source}（信任带：{trust}）")
    if exec_ok is True:
        lines.append("执行结果：成功")
    elif exec_ok is False:
        lines.append("执行结果：失败")
    else:
        lines.append("执行结果：未执行（需上层规划）")
    if needs_llm and not llm_used:
        lines.append(
            "说明：当前为无 LLM 模式且逻辑未命中，已按设计拒绝静默调用大模型。"
            "开启「GUI 允许 LLM 增强」后可启用文本/视觉兜底。"
        )
    if note:
        lines.append(f"备注：{note}")
    learning = result.get("learning") or {}
    if learning.get("status") == "done":
        lines.append(
            f"学习：校准命中 {learning.get('calibrated')} 个控件，"
            f"待匹配 {learning.get('pending')} 个，反向建图 {learning.get('reverse_built')} 个"
        )
    return "\n".join(lines)


class AutomateTool(Tool):
    """对外单一入口：表达 GUI 自动化目的，引擎内部完成推理+执行+回写。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="automate",
            description=(
                "图形界面自动化：用自然语言描述你想在指定软件里完成的操作"
                "（如「在记事本保存文件」「打开浏览器设置」）。系统自动感知界面、"
                "推理操作路径并执行，无需你给出具体坐标。注意：这会在真实窗口上产生"
                "点击/输入，请仅对当前可信窗口使用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {
                        "type": "string",
                        "description": "目标软件标识（如 notepad / chrome / wechat）。已知软件走 UIA/DOM 直驱；未知软件自动降级感知。",
                    },
                    "intent": {
                        "type": "string",
                        "description": "用自然语言描述要达成的目的，例如「点击设置按钮并切换到深色模式」。",
                    },
                },
                "required": ["software_id", "intent"],
            },
            event_type="desktop.control",
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "", intent: str = "", **kwargs: Any) -> str:
        if not software_id or not intent:
            return "参数缺失：automate 需要 software_id 与 intent。"
        # 感知首步（⑦点）：枚举桌面、选目标窗口、聚焦，避免误操错窗。
        desktop_ctx = None
        target_hwnd = 0
        focused = False
        try:
            desktop_ctx = perceive_desktop()
            target_hwnd = select_target_window(software_id, desktop_ctx)
            focused = ensure_foreground(target_hwnd) if target_hwnd else False
        except Exception as exc:
            _LOGGER.warning("桌面感知首步失败，降级为不指定窗口: %s", exc)
        # 后台接触式采集（⑧点）：仅空闲时只读 UIA 树蒸馏进 Atlas，不干扰不降级 OCR。
        try:
            scan = background_scan.maybe_background_scan(target_hwnd or None)
            if scan.get("scanned"):
                _LOGGER.info("后台接触式采集：%s 蒸馏 %d 节点", scan.get("software_id"), scan.get("nodes"))
        except Exception as exc:
            _LOGGER.warning("后台接触式采集跳过: %s", exc)
        planner = await _build_llm_planner()
        try:
            result = await execute_gui_intent(
                software_id, intent, llm_planner_fn=planner, target_hwnd=target_hwnd)
        except Exception as exc:
            return f"自动化执行异常：{type(exc).__name__}: {exc}"
        # 学习侧效应（fail-soft，纯逻辑）：聚合校准闭环 + 反向建图，把真实点击转化为地图知识。
        try:
            cal = atlas_calibration.calibrate_once()
            learning = {"calibrated": 0, "pending": 0, "reverse_built": 0, "status": cal.get("status")}
            if cal.get("status") == "done":
                learning.update({"calibrated": cal.get("matched"), "pending": cal.get("pending")})
                learning["reverse_built"] = reverse_builder.reverse_build_from_pending()
            result["learning"] = learning
        except Exception as exc:
            _LOGGER.warning("校准/反向建图跳过: %s", exc)
        # 附加桌面上下文供结果展示
        result["desktop"] = {
            "window_count": (desktop_ctx or {}).get("count", 0),
            "foreground_hwnd": (desktop_ctx or {}).get("foreground_hwnd", 0),
            "target_hwnd": target_hwnd,
            "focused": focused,
        }
        return _format_result(result)


# ── 砖块注册 ──────────────────────────────────────────────────
automation_brick = Brick(
    manifest=BrickManifest(
        name="automation",
        title="GUI 自动化",
        description="对外单一入口 automate，对内聚合桌面 GUI 感知/推理/执行能力。",
        bus_type="pcie",
    ),
    capabilities={},
)

# 注册砖块（主板视图可见）+ 直接把 automate 注册进全局工具表（与导入顺序无关，
# 因 agent 砖的 agent_tools 返回整个注册表，任何已注册工具 agent 均可用）。
registry.register(automation_brick)
get_registry().register(AutomateTool())

# 常驻点击采集钩子随砖加载启动（fail-soft）：被动记录用户真实点击用于地图校准，
# 不抢焦点、不截图、不 OCR。uiautomation 事件订阅不可用则静默跳过。
click_collector.start_click_collector()