"""动作执行 mixin：click/type/press/hotkey/check/close/verify，及 click 的 L0-L3 容错分解。"""
import time

import pyautogui
from ..desktop_control import (
    click_point, focus_window, hotkey, is_electron_app,
    press_key, type_text,
)
from ..executor_locator import find_control_direct, read_toggle_state, close_window
from ..executor_ladder import (
    try_click_direct, try_setvalue_direct,
    vlc_fallback_enabled, llm_click_fallback_enabled,
)
from ..world_model_cache.coord_memory import region_argmax


class _ClickMixin:
    """动作原语与 click 的多级容错：定向/UIA直驱/OCR+区域消歧/全树/VLC。"""

    def _act_check(self, step: dict) -> tuple[bool, str, bool]:
        """状态先验：读取开关状态；stop_if 命中则短路停止后续步骤（目标已达成）。"""
        hwnd, _, _ = self._resolve_target(step)
        if not hwnd:
            return False, "找不到窗口，无法检查状态", False
        state = read_toggle_state(hwnd, step.get("automation_id", ""))
        label = step.get("name") or step.get("automation_id")
        if state == -1:
            return False, f"{label} 未找到或不是开关控件（check 仅用于开关/切换类）", False
        text = f"开关 {label} 状态：{'开' if state == 1 else '关'}"
        stop_if = step.get("stop_if")
        if stop_if is not None and state == int(stop_if):
            return True, text + "（=stop_if 目标态，停止后续步骤）", True
        return True, text, False

    def _act_close(self, step: dict) -> tuple[bool, str, bool]:
        """用完清理：关闭目标窗口（点击关闭按钮/Alt+F4 兜底）。"""
        hwnd, _, _ = self._resolve_target(step)
        if not hwnd:
            return False, "找不到窗口，无法关闭", False
        ok = close_window(hwnd)
        return ok, f"关闭窗口 {step.get('target', '') or hwnd} {'成功' if ok else '失败'}", False

    def _act_verify(self, step: dict) -> tuple[bool, str, bool]:
        """鲁棒性原语：廉价 UIA 校验控件是否存在（~10ms/个，不碰 OCR）。
        供 LLM 确认状态而无需 describe_window 全量感知。"""
        hwnd, _, _ = self._resolve_target(step)
        if not hwnd:
            return False, "找不到窗口，无法校验", False
        idents = self._normalize_identifiers([{
            "name": step.get("name", ""),
            "automation_id": step.get("automation_id", ""),
            "control_type": step.get("control_type", ""),
        }])
        res = self._verify_controls_uia(hwnd, idents)
        label = step.get("name") or step.get("automation_id") or step.get("control_type")
        exists = bool(res.get("present"))
        return True, f"校验 {label}: {'存在' if exists else '不存在'}", False

    def _act_click(self, step: dict, loc: tuple[int, int], hwnd: int, level: str) -> tuple[bool, str]:
        x, y = loc
        self._last_hwnd = hwnd
        self._note_self_move(x, y)
        focus_window(hwnd)
        time.sleep(0.05)
        clicked = click_point(x, y, hwnd=hwnd)
        if not clicked:
            return False, (f"点击未送达真实桌面（隔离会话/无输入桌面），坐标 ({x},{y}) 未生效，"
                           f"请改用键盘路径或手动操作")
        return True, f"[{level}] 点击 {step.get('name') or step.get('automation_id')} @({x},{y})"

    def _act_simple(self, action: str, step: dict) -> tuple[bool, str, bool]:
        try:
            if action == "type":
                text = step.get("text", "")
                name = step.get("name", "")
                aid = step.get("automation_id", "")
                # 档1 节点操控：步骤带定位标识且能定位到控件时，优先用 UIA ValuePattern 设值
                if (name or aid) and text:
                    hwnd, _, _ = self._resolve_target(step)
                    if hwnd:
                        ok, msg = try_setvalue_direct(
                            hwnd, name, aid, step.get("control_type", ""), text)
                        if ok:
                            return True, f"[U1] {msg}", False
                type_text(text)
                return True, f"输入文本 {len(text)} 字符", False
            if action == "press":
                key = step.get("key", "")
                (press_key(int(key)) if key.isdigit() else pyautogui.press(key.lower()))
                return True, f"按下 [{key}]", False
            if action == "hotkey":
                keys = step.get("keys") or []
                if not isinstance(keys, list) or not keys:
                    return False, "hotkey 需要 keys 列表", False
                # pyautogui 键名全小写（LLM 常给 'Home'/'Enter' 等首字母大写，归一化避免静默失效）
                hotkey(*[str(k).lower() for k in keys])
                return True, f"组合键 {'+'.join(str(k) for k in keys)}", False
        except Exception as exc:
            return False, f"{action} 失败: {exc}", False
        return False, "未识别动作参数", False

    # ── click 多级容错分解 ───────────────────────────────

    def _run_click(self, step: dict) -> tuple[bool, str, bool]:
        """click 主入口：解析窗口→Electron 特判→定向定位→兜底→执行。"""
        hwnd, key, wtitle = self._resolve_target(step)
        if not hwnd:
            return False, f"找不到窗口：{step.get('target', '前台')}", False
        sid = self._sid(hwnd)
        if is_electron_app(hwnd):
            return self._run_click_electron(step, hwnd, key, wtitle, sid)
        loc, level, memory_hit = self._locate_click(step, hwnd, key, sid)
        if loc is None:
            loc, level = self._resolve_fallback(step, hwnd, key, wtitle, sid)
        if loc is None:
            return self._resolve_llm_vlc(step, hwnd)
        return self._perform_click(step, hwnd, loc, level, memory_hit, key)

    def _run_click_electron(self, step, hwnd, key, wtitle, sid) -> tuple[bool, str, bool]:
        """Electron/Chromium：禁用 UIA 遍历，强制 OCR 兜底（L3）定位。"""
        cands = self._ocr_candidates(step, wtitle, hwnd)
        chosen = region_argmax(sid or self._sid(hwnd), key, cands) if cands else None
        if chosen is None:
            # UIA 不可取且 OCR 未命中：交档3 LLM 语义 / 档4 VLC 视觉末端兜底链
            return self._resolve_llm_vlc(step, hwnd)
        return *self._act_click(step, chosen["screen"], hwnd, "L3"), False

    def _locate_click(self, step, hwnd, key, sid) -> tuple:
        """非 Electron 定向定位：预取→跨会话记忆→UIA 直查→重绘重试。"""
        loc = self._consume_prefetch(key)
        level, memory_hit = "L0", False
        if loc:
            self._stats["prefetch_hits"] += 1
        else:
            mem_loc = self._coord_memory_lookup(step, hwnd, key)
            if mem_loc:
                loc, level, memory_hit = mem_loc, "LM", True
                self._stats["coord_memory_hits"] = self._stats.get("coord_memory_hits", 0) + 1
            else:
                loc = find_control_direct(
                    hwnd, name=step.get("name", ""), automation_id=step.get("automation_id", ""),
                    control_type=step.get("control_type", ""))
        if loc and not memory_hit:
            cached = self._cache.get(hwnd, {}).get("locations", {}).get(key)
            level = "L0" if cached == loc else "L2"
            if level == "L0":
                self._stats["cache_hits"] += 1
            self._learn(hwnd, key, loc)
        elif loc and memory_hit:
            self._learn(hwnd, key, loc)
        if loc is None:
            self._stats["redraw_retries"] += 1
            time.sleep(0.3)  # 界面重绘中，重试定向（仅普通查找路径触发）
            loc = find_control_direct(
                hwnd, name=step.get("name", ""), automation_id=step.get("automation_id", ""),
                control_type=step.get("control_type", ""))
        return loc, level, memory_hit

    def _resolve_fallback(self, step, hwnd, key, wtitle, sid) -> tuple:
        """档2/全树兜底：OCR+区域概率消歧（L3）→ 全树模糊（L2）。"""
        cands = self._ocr_candidates(step, wtitle, hwnd)
        chosen = region_argmax(sid, key, cands) if cands else None
        if chosen is not None:
            self._learn(hwnd, key, chosen["screen"])
            return chosen["screen"], "L3"
        loc = self._locate_fulltree(step, hwnd)
        if loc:
            self._learn(hwnd, key, loc)
            return loc, "L2"
        return None, ""

    def _llm_or_fail(self, step, hwnd) -> tuple[bool, str, bool]:
        """档3 LLM 语义点击兜底（受 llm_click_fallback_enabled 门控）或返回诊断。"""
        enabled, reason = llm_click_fallback_enabled()
        if enabled:
            llm_ok, lmsg = self._llm_decide_and_click(step, hwnd)
            if llm_ok:
                return True, f"[LLM] {lmsg}", False
        return False, (f"定位失败：UIA/OCR 均未命中控件 {step.get('name') or step.get('automation_id')}"
                       f"（定向/OCR 语义均未命中）；{reason}"), False

    def _resolve_llm_vlc(self, step, hwnd) -> tuple[bool, str, bool]:
        """末端兜底链：档3 LLM 语义 → 档4 VLC 视觉。均失败则档4 返回最终诊断。"""
        ok_llm, msg_llm, _ = self._llm_or_fail(step, hwnd)
        if ok_llm:
            return True, msg_llm, False
        return self._vlc_or_fail(step, hwnd)

    def _vlc_or_fail(self, step, hwnd) -> tuple[bool, str, bool]:
        """档4 VLC 视觉兜底（受双门控）或返回定位失败诊断。"""
        enabled, reason = vlc_fallback_enabled()
        if enabled:
            vlc_ok, vmsg = self._vlc_decide_and_click(step, hwnd)
            if vlc_ok:
                return True, f"[VLC] {vmsg}", False
        return False, (f"定位失败：找不到控件 {step.get('name') or step.get('automation_id')}"
                       f"（定向/OCR/LLM 语义/全树均未命中）；{reason}"), False

    def _perform_click(self, step, hwnd, loc, level, memory_hit, key) -> tuple[bool, str, bool]:
        """最终执行：档1 节点操控优先，否则坐标点击 + 预测校验回写。"""
        action = (step.get("action") or "").lower()
        if level != "L0":
            direct_ok, direct_msg = try_click_direct(
                hwnd, step.get("name", ""), step.get("automation_id", ""), step.get("control_type", ""))
            if direct_ok:
                self._write_coord_memory(step, hwnd, loc, key)
                self._stats["levels"]["U1"] = self._stats["levels"].get("U1", 0) + 1
                vmsg = self._verify_after_click(step, hwnd)
                if vmsg:
                    self._stats["predicted_verified"] = self._stats.get("predicted_verified", 0) + 1
                return True, f"[U1] {direct_msg}" + (f"；{vmsg}" if vmsg else ""), False
        self._write_coord_memory(step, hwnd, loc, key)
        self._stats["levels"][level] = self._stats["levels"].get(level, 0) + 1
        ok, msg = self._act_click(step, loc, hwnd, level)
        if ok and action == "click":
            vmsg = self._verify_after_click(step, hwnd)
            if vmsg:
                msg = f"{msg}；{vmsg}"
                self._stats["predicted_verified"] = self._stats.get("predicted_verified", 0) + 1
        return ok, msg, False
