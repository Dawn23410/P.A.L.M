"""Atlas 认知地图工具组（AI 规划输入 + 实时定位桥）。

两类工具：
- 规划输入：get_cognitive_map / list_software —— 把持久化 Atlas 静态地图喂给 LLM，
  让其知道「目标软件有什么 UI/能力」，但**绝不**把地图当运行时状态。
- 执行桥：click_element —— 重新 build_world_model 拿到实时树，按名称/automation_id
  解析控件屏幕坐标后真实点击，补全 OCR 文字工具够不到的图标/无文本控件。

所有工具 fail-soft：storage 砖不可用时返回友好提示，不抛异常。
"""
from __future__ import annotations

import json
import logging

from palm._core.tooling import Tool, ToolSpec
from .world_model_cache.registry import SoftwareRegistry, list_software_ids
from .world_model_cache.transition_model import (
    record_transition, query_software_expected, extract_control_keys)
from .world_model import build_world_model, build_uia_tree, find_control, _iter_nodes
from .desktop_control import click_point, find_window, is_electron_app, get_window_exe
from .world_model_cache.reasoning_hub import infer_route, confirm_and_save, linkage_report, _decide
from .world_model_cache.path_memory import report_execution
from .automation_orchestrator import execute_gui_intent

_LOGGER = logging.getLogger(__name__)

_NOISE_CT = {"WindowControl", "TitleBar", "MenuBarControl", "MenuItemControl",
             "TextControl", "ToolTipControl", "EditControl", "ListControl",
             "ScrollBarControl", "PaneControl", "GroupControl"}
_NOISE_NAME = {"设置", "系统", "最小化", "最大化", "关闭", "搜索框，查找设置"}


# 可交互控件类型（超限裁剪时优先保留，保证 Ribbon 命令等按钮不丢）
_INTERACTIVE_CT = {"ButtonControl", "SplitButtonControl", "CheckBoxControl",
                   "RadioButtonControl", "TabItemControl", "HyperlinkControl",
                   "ComboBoxControl", "ListBoxControl", "TreeItemControl"}


def _controls_summary(tree: dict, limit: int = 120) -> list:
    """从世界模型树提取可见内容控件清单（过滤标题栏/搜索框等噪声），供 LLM 规划。

    limit 默认 120：Word 161 节点下 Ribbon 命令按钮在 60 之后仍可能漏（实测恰在边界），
    提上限并支持超限时按可交互类型优先裁剪，保证复杂应用（Office/Ribbon）命令不丢。
    """
    out, seen = [], set()
    for node in _iter_nodes(tree):
        name = (node.get("name") or "").strip()
        aid = node.get("automation_id") or ""
        ct = node.get("control_type") or ""
        if not (name or aid) or not node.get("visible"):
            continue
        if ct in _NOISE_CT or name in _NOISE_NAME:
            continue
        key = f"{name}|{aid}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "automation_id": aid, "control_type": ct})
        if len(out) >= limit:
            break
    if len(out) <= limit:
        return out
    # 超限：可交互控件优先，其余按类型排序后截断
    interactive = [c for c in out if c["control_type"] in _INTERACTIVE_CT]
    rest = [c for c in out if c["control_type"] not in _INTERACTIVE_CT]
    return (interactive + rest)[:limit]


def _format_level(level: dict, detail: bool) -> dict:
    """把单个 level 压成 LLM 友好的控件清单（动态占位只标类型不标值）。"""
    nodes = level.get("nodes", []) or []
    controls = []
    for n in nodes:
        role = n.get("role")
        item = {
            "identity": n.get("identity"),
            "type": n.get("control_type"),
            "name": n.get("name") or "",
            "role": role,
        }
        # 动态占位节点只暴露「此处有可变状态」，绝不暴露具体值（开/关、文本、计数）。
        if role and role != "static":
            item["dynamic"] = n.get("dynamic")
        if detail:
            item["rect_relative"] = n.get("rect_relative")
        controls.append(item)
    return {
        "level_id": level.get("level_id"),
        "control_count": len(controls),
        "controls": controls,
    }


def _format_entry(entry: dict, level_id: str | None, detail: bool) -> dict:
    """把整个软件条目压成规划用摘要。"""
    levels = entry.get("levels", {}) or {}
    if level_id:
        lv = levels.get(level_id)
        level_block = [_format_level(lv, detail)] if lv else []
    else:
        level_block = [_format_level(lv, detail) for lv in levels.values()]
    return {
        "software_id": entry.get("software_id"),
        "exe": entry.get("exe"),
        "title_sample": entry.get("title_sample"),
        "level_count": len(level_block),
        "levels": level_block,
    }


def _entry_is_empty(entry: dict) -> bool:
    """条目无任何 level/节点 → 视为 Atlas 尚未建立。"""
    levels = entry.get("levels", {}) or {}
    return not any((lv.get("nodes") for lv in levels.values()))


class GetCognitiveMapTool(Tool):
    """获取某软件持久化的 Atlas 静态认知地图（供 AI 规划，非运行时状态）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_cognitive_map",
            description=(
                "获取某个软件持久化的「认知地图」（Atlas 静态 UI 地图），用于 AI 跨软件/跨层级"
                "规划时了解「该软件有什么界面与控件」。地图只描述结构与静态标签，"
                "开关的开/关、状态文本、列表内容等动态值一律不暴露——规划只能依据结构。"
                "Atlas 不是运行时状态：拿到地图规划后，真实点击前仍需由 GUI 工具实时重扫屏幕定位。"
                "software_id 一般为 exe 名归一化（如 notepad / windows_settings）；"
                "若该软件尚未建图，会提示先让它跑一次世界模型以自动建图。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {
                        "type": "string",
                        "description": "目标软件 id（如 notepad）。留空则改用 list_software 罗列已知软件",
                    },
                    "level_id": {
                        "type": "string",
                        "description": "只看某个层级（如 default）；留空返回全部层级",
                    },
                    "detail": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否附带相对坐标（窗口内归一化矩形），默认只给结构",
                    },
                },
                "required": [],
            },
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "", level_id: str = "",
                      detail: bool = False) -> str:
        if not software_id:
            return "未指定 software_id；如需查看已建图软件请改用 list_software 工具。"
        entry = SoftwareRegistry().load(software_id)
        if _entry_is_empty(entry):
            return (
                f"Atlas 中尚无「{software_id}」的静态地图。请先让该软件实际跑一次世界模型"
                f"（如用 focus_window/截图或 GUI 操作触发 build_world_model），Atlas 会自动蒸馏建图，"
                f"之后即可用本工具规划。"
            )
        payload = _format_entry(entry, level_id or None, detail)
        return json.dumps(payload, ensure_ascii=False, indent=2)


class ListSoftwareTool(Tool):
    """罗列已建图（持久化 Atlas）的软件清单。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_software",
            description=(
                "罗列当前已建立 Atlas 静态认知地图的全部软件（software_id 列表），"
                "并附每个软件的窗口标题样本与控件数量，帮助规划前先确认「有没有目标软件的地图」。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "with_summary": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否附带每个软件的标题样本与控件总数",
                    },
                },
                "required": [],
            },
            permission="desktop.control",
        )

    async def execute(self, with_summary: bool = True) -> str:
        ids = list_software_ids()
        if not ids:
            return "尚未建立任何 Atlas 认知地图（让 GUI 工具实际跑过世界模型后会自动建图）。"
        if not with_summary:
            return json.dumps({"software_ids": ids, "count": len(ids)},
                              ensure_ascii=False, indent=2)
        rows = []
        for sid in ids:
            entry = SoftwareRegistry().load(sid)
            levels = entry.get("levels", {}) or {}
            total = sum(len(lv.get("nodes", []) or []) for lv in levels.values())
            rows.append({
                "software_id": sid,
                "title_sample": entry.get("title_sample"),
                "level_count": len(levels),
                "control_count": total,
            })
        return json.dumps({"software_ids": ids, "count": len(ids), "details": rows},
                          ensure_ascii=False, indent=2)


class ClickElementTool(Tool):
    """按名称/automation_id 在当前窗口实时世界模型里定位控件并真实点击（执行桥）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="click_element",
            description=(
                "在目标窗口的「实时」世界模型里按控件名称或 automation_id 解析出屏幕坐标并真实点击。"
                "相比 click_text（依赖 OCR 文字），本工具走 UIA 结构树，能稳定命中无文字的图标按钮、"
                "工具栏项、菜单项等 OCR 漏掉的控件。每次调用都重新 build_world_model 实时定位，"
                "不与 Atlas 静态地图混用——Atlas 只用于规划，本工具负责落地。"
                "仅点击找到的第一个最精确匹配；若需坐标而不点击可设 click=false。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "控件名称/标签子串，如「保存」「设置」；可与 automation_id 二选一或并用",
                    },
                    "automation_id": {
                        "type": "string",
                        "description": "控件 automation_id（最精确）；留空则仅按名称匹配",
                    },
                    "control_type": {
                        "type": "string",
                        "description": "控件类型过滤，如 Button/MenuItem/TabItem（可选）",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标窗口标题子串或 hwnd；留空取前台窗口",
                    },
                    "click": {
                        "type": "boolean",
                        "default": True,
                        "description": "是否真实点击；false 仅返回解析到的坐标",
                    },
                },
                "required": [],
            },
            permission="desktop.control",
        )

    async def execute(self, name: str = "", automation_id: str = "",
                      control_type: str = "", target: str = "",
                      click: bool = True) -> str:
        if not name and not automation_id:
            return "未指定 name 或 automation_id，无法定位控件。"
        # 解析目标窗口句柄；Electron/Chromium 应用禁用 UIA 世界模型（遍历触发 ntdll）。
        hwnd = 0
        if target and isinstance(target, str):
            found = find_window(target)
            if found:
                hwnd = found[0]
        else:
            try:
                import uiautomation as auto
                hwnd = auto.GetForegroundControl().NativeWindowHandle
            except Exception:
                hwnd = 0
        if is_electron_app(hwnd):
            if name:
                try:
                    from .desktop_tools import ClickTextTool
                    _LOGGER.info("click_element 命中 Electron 应用，跳过 UIA 直接 OCR 点击 name=%r", name)
                    return await ClickTextTool().execute(text=name, window_title=target or "")
                except Exception as exc:
                    return f"Electron 应用 UIA 不可用，OCR 兜底也失败：{exc}"
            return ("Electron 应用 UIA 不可用且未提供 name，无法用 OCR 定位，"
                    "请改用 click_text 工具指定文字")
        try:
            model = build_world_model(target or None)
        except Exception as exc:
            return f"实时世界模型构建失败，无法定位：{exc}"
        node, center = find_control(
            model, name=name or None, automation_id=automation_id or None,
            control_type=control_type or None,
        )
        if node is None or center is None:
            # UIA 结构树未命中（无名图标按钮等 OCR 漏不掉的盲区）→ 回退 OCR 文字点击补位。
            if name:
                try:
                    from .desktop_tools import ClickTextTool
                    _LOGGER.info("click_element 结构定位失败，回退 OCR 点击 name=%r", name)
                    return await ClickTextTool().execute(text=name, window_title=target or "")
                except Exception as exc:
                    return (f"在实时世界中未找到匹配的控件（name={name!r} automation_id={automation_id!r}），"
                            f"且 OCR 兜底也失败：{exc}")
            return f"在实时世界中未找到匹配的控件（name={name!r} automation_id={automation_id!r}）。"
        cx, cy = center
        resolved = {
            "matched_name": node.get("name"),
            "control_type": node.get("control_type"),
            "automation_id": node.get("automation_id"),
            "center": [cx, cy],
            "image_confirmed": node.get("image_confirmed", False),
        }
        if not click:
            return json.dumps({"clicked": False, **resolved}, ensure_ascii=False, indent=2)
        hwnd = 0
        if target and isinstance(target, str):
            found = find_window(target)
            if found:
                hwnd = found[0]
        try:
            click_point(cx, cy, hwnd=hwnd)
        except Exception as exc:
            return f"控件已定位到 {center} 但点击失败：{exc}"
        return json.dumps({"clicked": True, **resolved}, ensure_ascii=False, indent=2)





class DescribeWindowTool(Tool):
    """实时界面感知：返回当前窗口的结构化控件清单（LLM 规划输入）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="describe_window",
            description=(
                "获取目标窗口的实时结构化感知（控件清单：name/automation_id/control_type）。"
                "mode=uia（默认）仅 UIA 结构，极快（几十 ms），适合每次开界面时的快速感知；"
                "mode=full 追加全屏 OCR（几十 ms~0.5s），能补 UIA 漏掉的图标/渲染文本，"
                "适合需要完整界面理解的建图/首次规划。返回控件清单 + meta（节点数/OCR框数/耗时）。"
                "规划前先调用本工具了解当前界面有什么，再生成 run_automation 步骤。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "窗口标题子串或 hwnd；空取前台窗口"},
                    "mode": {"type": "string", "enum": ["uia", "full"], "default": "uia",
                             "description": "uia=仅 UIA 结构；full=UIA+OCR 全量"},
                    "should_anticipate": {"type": "boolean", "default": False,
                                          "description": "是否附转移规律层先验：返回该软件历史高频控件清单，"
                                                         "供 LLM 规划时压缩上下文（命中先验可少扫全量）"},
                    "record_action": {"type": "string", "default": "",
                                      "description": "若非空，感知后把「本动作→当前界面控件集合」记入转移规律层"
                                                     "（经验式 dynamics：补足点击后出现什么的统计）"},
                    "verify_present": {"type": "array", "items": {"type": "string"},
                                      "description": "轻量校验模式：给定控件名/automation_id 列表，仅走 UIA 树确认存在与否"
                                                     "（不重建全量、不 OCR），用于动作后确认预测控件出现，"
                                                     "避免完整 describe_window 的全量感知开销"},
                },
                "required": [],
            },
            permission="desktop.control",
        )

    async def execute(self, target: str = "", mode: str = "uia",
                      should_anticipate: bool = False, record_action: str = "",
                      verify_present: list | None = None) -> str:
        import time as _t
        if isinstance(target, int):
            hwnd = target
        elif target:
            found = find_window(str(target))
            hwnd = found[0] if found else 0
        else:
            try:
                import uiautomation as auto
                hwnd = auto.GetForegroundControl().NativeWindowHandle
            except Exception:
                hwnd = 0
        if not hwnd:
            return json.dumps({"error": f"找不到窗口: {target or '前台'}"}, ensure_ascii=False)
        t0 = _t.perf_counter()
        if is_electron_app(hwnd):
            # Electron 应用 UIA 遍历触发 ntdll，禁用 UIA 感知，引导改用 OCR/截图工具。
            return json.dumps({
                "error": "该窗口为 Electron/Chromium 内核，UIA 结构树不可用（遍历会崩溃）；"
                         "请改用 take_screenshot / click_text 等 OCR 工具感知与操作界面",
                "electron_app": True,
            }, ensure_ascii=False)
        # 轻量校验模式：仅确认给定控件存在与否，走 UIA 树不重建全量、不 OCR（省感知开销）
        if verify_present:
            try:
                uia = build_uia_tree(hwnd)
                present, missing = [], []
                for v in verify_present:
                    if "|" in v:
                        ct, aid = v.split("|", 1)
                        ident = {"control_type": ct, "automation_id": aid, "name": aid}
                    else:
                        ident = {"name": v}
                    node, _ = find_control({"uia_tree": uia["tree"]},
                                           name=ident.get("name") or None,
                                           automation_id=ident.get("automation_id") or None,
                                           control_type=ident.get("control_type") or None)
                    (present if node else missing).append(v)
                return json.dumps({
                    "verify_present": {"present": present, "missing": missing},
                    "meta": {"mode": "verify", "elapsed_ms": int((_t.perf_counter() - t0) * 1000)},
                }, ensure_ascii=False, indent=1)
            except Exception as _vp_err:
                return json.dumps({"error": f"轻量校验失败: {_vp_err}"            }, ensure_ascii=False)
        if mode == "full":
            model = build_world_model(hwnd, mode="window")
            controls = _controls_summary(model.get("uia_tree", {}))
            meta = {"mode": "full", "uia_nodes": model["meta"]["uia_node_count"],
                    "ocr_boxes": model["meta"]["ocr_box_count"],
                    "elapsed_ms": int((_t.perf_counter() - t0) * 1000)}
        else:
            uia = build_uia_tree(hwnd)
            controls = _controls_summary(uia["tree"])
            meta = {"mode": "uia", "uia_nodes": uia["node_count"], "ocr_boxes": 0,
                    "elapsed_ms": int((_t.perf_counter() - t0) * 1000)}
        # 转移规律层：记录 / 先验（不影响主感知结果，失败静默降级）
        sid = get_window_exe(hwnd) or "unknown"
        if record_action:
            try:
                record_transition(sid, record_action, extract_control_keys(controls))
                meta["transition_recorded"] = record_action
            except Exception as _tr_err:
                _LOGGER.warning("转移规律记录失败: %s", _tr_err)
        if should_anticipate:
            try:
                meta["expected_controls"] = query_software_expected(sid)
            except Exception as _an_err:
                _LOGGER.warning("转移规律先验查询失败: %s", _an_err)
        return json.dumps({"controls": controls, "meta": meta}, ensure_ascii=False, indent=1)


# ── 注册列表 ───────────────────────────────────────────

class PlanRouteTool(Tool):
    """推理中枢入口：尝试不调用 LLM 直接给出 GUI 操作路线（规划前置，省 LLM 调用）。

    三级推断：① 路线记忆命中（历史 LLM 成功/纠正路径）→ ② 语义关键词推断（Atlas 能力标签
    纯规则匹配）→ ③ 两者皆不足返回 needs_llm=true + 紧凑上下文，由 LLM 规划一次后
    confirm_and_save 落盘。返回的 steps 可直接交给 run_automation 执行。
    """

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="plan_route",
            description=(
                "推理中枢：给定软件与意图，尽量不调用 LLM 直接产出 GUI 操作路线。"
                "优先复用历史成功路线（记忆）或用 Atlas 能力标签做语义关键词推断；"
                "仅当两者都不足时才 needs_llm=true 并返回紧凑上下文，供 LLM 规划一次后"
                "用 confirm_route 落盘（下次同意图即可跳过 LLM）。"
                "返回字段：source(memory/inferred/llm_fallback)、trust(可信等级)、needs_llm、"
                "verify_after(执行后是否需校验)、steps（run_automation 步骤）、confidence、"
                "stale（路线结构是否因软件更新过期）、context(含 linkage 跨层佐证)。"
                "trust 三档：trusted=纯推理直执行（免 LLM）；verify=推理执行但强制事后校验；"
                "weak=仍走 LLM（可带 steps 作建议上下文）。单次 LLM 命中不会直接封顶信任，"
                "须经多次佐证/执行成功回写才会升入 trusted——规划前应先调用本工具省 LLM 调用与延迟。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {
                        "type": "string",
                        "description": "目标软件 id（如 notepad / windows_settings）；须已建 Atlas 地图",
                    },
                    "intent": {
                        "type": "string",
                        "description": "自然语言意图，如「保存文件」「打开设置」「关掉蓝牙」",
                    },
                },
                "required": ["software_id", "intent"],
            },
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "", intent: str = "") -> str:
        if not software_id or not intent:
            return json.dumps({"error": "software_id 与 intent 均必填"}, ensure_ascii=False)
        result = infer_route(software_id, intent)
        return json.dumps(result, ensure_ascii=False, indent=2)


class ConfirmRouteTool(Tool):
    """把 LLM 规划+执行结果回写路线记忆（验证后落盘，下次同意图免 LLM）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="confirm_route",
            description=(
                "路线验证落盘：LLM 经 plan_route 拿到 needs_llm 后自行规划并执行，"
                "若执行成功(success=true)把步骤存为正常路线；若曾纠正失败步骤(recovered_steps)则存异常处理路线。"
                "下一次相同/近似意图即可被 plan_route 直接命中，免去 LLM 规划调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {"type": "string", "description": "目标软件 id"},
                    "intent": {"type": "string", "description": "与 plan_route 一致的意图原文"},
                    "steps": {"type": "array", "description": "本次实际执行的 run_automation 步骤数组"},
                    "success": {"type": "boolean", "default": True, "description": "执行是否成功"},
                    "source": {"type": "string", "default": "llm",
                               "description": "路线来源（llm/ inferred）"},
                    "exception_type": {"type": "string", "description": "若失败，异常类型简述"},
                    "recovered_steps": {"type": "array",
                                        "description": "若曾纠正，纠正后的可用步骤数组"},
                },
                "required": ["software_id", "intent", "steps"],
            },
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "", intent: str = "",
                      steps: list | None = None, success: bool = True,
                      source: str = "llm", exception_type: str = "",
                      recovered_steps: list | None = None) -> str:
        ok = confirm_and_save(software_id, intent, steps or [], success,
                              source, exception_type, recovered_steps)
        return json.dumps({"saved": ok, "software_id": software_id},
                          ensure_ascii=False)


class ReportRouteResultTool(Tool):
    """执行结果回写：把一次实际执行的成败反向调制路线置信度（越用越准闭环的关键写入口）。

    与 confirm_route 分工：confirm_route 负责「首次/纠正落盘」，本工具负责「后续每次执行」
    成功→加信任、失败→降信任。规划器在 run_automation 结束后务必调用，让置信度真实反映
    执行情况，而非仅由 LLM 落盘次数决定。失败且曾纠正时一并走 confirm_route 落盘异常路线。
    """

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="report_route_result",
            description=(
                "执行结果回写：run_automation 结束后调用，把成败反向调制 plan_route 产出的路线置信度。"
                "success=true→加信任（越用越准）；success=false→降信任（防偶然成功路线被高估）。"
                "若本次曾纠正失败步骤，传 recovered_steps 一并落盘异常处理路线。"
                "返回更新后的置信度与信任等级，供下次 plan_route 决策参考。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {"type": "string", "description": "目标软件 id"},
                    "intent": {"type": "string", "description": "与 plan_route 一致的意图原文"},
                    "success": {"type": "boolean", "default": True,
                                "description": "本次 run_automation 是否整体成功"},
                    "exception_type": {"type": "string", "description": "若失败，异常类型简述"},
                    "recovered_steps": {"type": "array",
                                        "description": "若曾纠正，纠正后的可用步骤数组"},
                },
                "required": ["software_id", "intent", "success"],
            },
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "", intent: str = "",
                      success: bool = True, exception_type: str = "",
                      recovered_steps: list | None = None) -> str:
        if not software_id or not intent:
            return json.dumps({"error": "software_id 与 intent 均必填"}, ensure_ascii=False)
        ok = report_execution(software_id, intent, success)
        if not success and recovered_steps:
            confirm_and_save(software_id, intent, [], False, "llm",
                             exception_type, recovered_steps)
        mem = query_route(software_id, intent) if ok else None
        conf = mem["confidence"] if mem else 0.0
        return json.dumps({"updated": ok, "confidence": conf,
                          "trust": _decide(conf, bool(mem and mem.get("stale"))),
                          "software_id": software_id}, ensure_ascii=False)


class LinkageReportTool(Tool):
    """全局联动度审计：聚合 Atlas/路线/转移/坐标四层子系统的覆盖与相互佐证程度。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="linkage_report",
            description=(
                "全局联动度：查看某软件四层子系统（Atlas 静态地图 / 路线记忆 / 转移规律 / 坐标记忆）"
                "的实际覆盖与相互佐证率。linkage_score 越高代表各层真正联动、越用越准越快；"
                "缺失子系统会拉低分值，提示该补哪一层数据。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "software_id": {"type": "string", "description": "目标软件 id"},
                },
                "required": ["software_id"],
            },
            permission="desktop.control",
        )

    async def execute(self, software_id: str = "") -> str:
        if not software_id:
            return json.dumps({"error": "software_id 必填"}, ensure_ascii=False)
        return json.dumps(linkage_report(software_id), ensure_ascii=False, indent=2)

