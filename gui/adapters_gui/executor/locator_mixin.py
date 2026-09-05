"""定位辅助 mixin：目标窗口解析、软件标识、运行时/跨会话坐标记忆、OCR 候选采集。"""
import ctypes
import tempfile
import os

import uiautomation as auto

from ..desktop_control import find_window, get_window_exe
from ..world_model import build_uia_tree, find_control
from ..world_model_cache.coord_memory import save_coord, get_coord
from ..world_model_cache.transition_model import (
    _NOISE_CT, _NOISE_NAME, _control_key)
from .constants import _step_key, _LOGGER

user32 = ctypes.windll.user32


class _LocatorMixin:
    """窗口/坐标定位辅助：解析目标窗、统一 sid、坐标记忆读写、OCR 候选。"""

    def _resolve_target(self, step: dict) -> tuple[int, str, str]:
        """解析目标窗口：返回 (hwnd, step_key, 窗口真实标题)。

        回退链：显式 hwnd → 标题子串 → 同软件缓存窗口（标题易变场景）→ 前台窗口。
        """
        target = step.get("target", "")
        if isinstance(target, int):
            hwnd = target
        elif target:
            found = find_window(str(target))
            if found:
                hwnd = found[0]
            else:
                try:
                    # SystemSettings 的 Win32 标题常为空，GetWindowTextW 抓不到 → UIA 枚举回退
                    hwnd = next(w.NativeWindowHandle for w in auto.GetRootControl().GetChildren()
                                if str(target).lower() in (w.Name or "").lower())
                except (StopIteration, Exception):
                    hwnd = 0
                if not hwnd:
                    hwnd = self._resolve_by_software(str(target))
                if not hwnd and self._last_hwnd and user32.IsWindow(self._last_hwnd):
                    hwnd = self._last_hwnd  # 同一规划链内窗口标题变化（如输入后加 *）→ 沿用最近窗口
                if not hwnd:
                    return 0, _step_key(step), self._foreground_hint()
        else:
            try:
                hwnd = auto.GetForegroundControl().NativeWindowHandle
            except Exception:
                return 0, _step_key(step), ""
        try:
            wtitle = auto.ControlFromHandle(hwnd).Name or ""
        except Exception:
            wtitle = ""
        return hwnd, _step_key(step), wtitle

    def _resolve_by_software(self, target: str) -> int:
        """回退：按 exe 名在缓存找同软件存活窗口（标题变化时 exe 名稳定）。"""
        t = target.lower()
        for hwnd, entry in self._cache.items():
            sid = entry.get("software_id") or ""
            if sid and (sid in t or t in sid) and user32.IsWindow(hwnd):
                return hwnd
        return 0

    def _foreground_hint(self) -> str:
        """窗口找不到时的诊断提示：当前前台窗口标题 + 已缓存软件。"""
        try:
            hint = f"前台窗口: {auto.GetForegroundControl().Name or ''}"
        except Exception:
            hint = "无法读取前台窗口"
        sids = sorted({e.get("software_id", "") for e in self._cache.values() if e.get("software_id")})
        return hint + (f"；已缓存软件: {','.join(sids)}" if sids else "")

    def _sid(self, hwnd: int) -> str:
        """坐标/转移规律层的软件标识：编排器下传优先，否则回退窗口 exe 派生（保持旧行为）。

        统一 sid 是联动度正确的前提——路线层用 software_id，坐标/转移层若用 exe 名会错配，
        导致 linkage_report 按 software_id 查不到坐标/转移数据（coord_count/transition_samples 恒为 0）。
        """
        if self._sid_override:
            return self._sid_override
        return self._cache.get(hwnd, {}).get("software_id") or get_window_exe(hwnd)

    def _learn(self, hwnd: int, key: str, loc: tuple[int, int]) -> None:
        """增量学习：把本次解析到的坐标写入运行时缓存，下次同窗口直接命中。"""
        entry = self._cache.setdefault(hwnd, {"locations": {}})
        if not entry.get("software_id"):
            entry["software_id"] = self._sid_override or get_window_exe(hwnd)
        entry["locations"][key] = loc

    def _window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """取窗口屏幕矩形 (x, y, w, h)；最小化/无效返回 None。"""
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return (rect.left, rect.top, w, h)

    def _coord_memory_lookup(self, step: dict, hwnd: int, key: str) -> tuple[int, int] | None:
        """跨会话坐标记忆：denormalize 历史归一化坐标 + O(1) 命中测试，跳过 UIA 树遍历。

        仅当步骤含可识别 name/automation_id（能核验命中身份）时才用，身份不符立即回退
        到常规 find_control_direct —— 绝不盲点（窗口移动/缩放导致坐标错位时安全降级）。
        """
        name = step.get("name") or ""
        aid = step.get("automation_id") or ""
        if not (name or aid):
            return None
        sid = self._sid(hwnd)
        if not sid:
            return None
        coord = get_coord(sid, key)
        if coord is None:
            return None
        rect = self._window_rect(hwnd)
        if rect is None:
            return None
        wx, wy, ww, wh = rect
        nx, ny, _, _ = coord
        cx, cy = int(wx + nx * ww), int(wy + ny * wh)
        try:
            el = auto.ControlFromPoint(cx, cy)
            if el is None or not el.Exists(0.5):
                return None
            if aid and el.AutomationId != aid:
                return None
            if name and name not in (el.Name or ""):
                return None
            ct = step.get("control_type") or ""
            if ct and ct not in str(el.ControlType):
                return None
            return (cx, cy)
        except Exception:
            return None

    def _write_coord_memory(self, step: dict, hwnd: int, loc: tuple[int, int], key: str) -> None:
        """跨会话坐标记忆回写：归一化当前绝对坐标，下次会话/重开窗直接命中（越用越快）。"""
        try:
            rect = self._window_rect(hwnd)
            if rect is None:
                return
            wx, wy, ww, wh = rect
            cx, cy = loc
            sid = self._sid(hwnd)
            if not sid:
                return
            save_coord(sid, key, (cx - wx) / ww, (cy - wy) / wh, 0.0, 0.0)
        except Exception:
            pass

    def _ocr_candidates(self, step: dict, wtitle: str, hwnd: int) -> list[dict]:
        """档2 OCR+点击预测：收集所有文字匹配候选，返回相对窗口归一化中心+屏幕中心+权重。

        用于 region_argmax 概率消歧：人类点击区域先验能排除超范围候选并选最优点，
        而非盲目取第一个 OCR 命中（设计：点击范围概率 + 无 LLM 消歧）。
        """
        name = step.get("name", "")
        if not name:
            return []
        try:
            shot = os.path.join(tempfile.gettempdir(), "executor_l3.png")
            import pyautogui
            pyautogui.screenshot(shot)
            from ..desktop_control import ocr_boxes
            boxes = ocr_boxes(shot) or []
            rect = self._window_rect(hwnd) or (0, 0, 1, 1)
            ww, wh = max(rect[2] - rect[0], 1), max(rect[3] - rect[1], 1)
            out: list[dict] = []
            for b in boxes:
                txt = (b.get("text") or "").strip()
                if name not in txt and txt not in name:
                    continue
                r = b.get("rect") or b.get("box") or b.get("bbox") or (0, 0, 0, 0)
                cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                nx, ny = (cx - rect[0]) / ww, (cy - rect[1]) / wh
                out.append({"center": (round(nx, 4), round(ny, 4)),
                            "screen": (int(cx), int(cy)), "weight": 1.0})
            return out
        except Exception as exc:
            _LOGGER.warning("OCR 候选采集失败: %s", exc)
            return []

    def _locate_ocr(self, step: dict, wtitle: str, hwnd: int = 0) -> tuple[int, int] | None:
        """L3 单点兼容：取 OCR 候选第一个（保持旧调用语义，复用 _ocr_candidates）。"""
        cands = self._ocr_candidates(step, wtitle, hwnd)
        return cands[0]["screen"] if cands else None

    def _locate_fulltree(self, step: dict, hwnd: int) -> tuple[int, int] | None:
        """全树模糊回退：定向查找按精确条件，LLM 给参可能子串/大小写不全 → 全树子串匹配。"""
        try:
            uia = build_uia_tree(hwnd)
            _, center = self._find_with_fallback(step, uia["tree"])
            return center
        except Exception:
            return None

    def _find_with_fallback(self, step: dict, tree: dict) -> tuple[dict | None, tuple[int, int] | None]:
        """定位分级：全条件→降 automation_id→降 control_type→纯 name，逐级放宽容忍 LLM 给参不精确。"""
        name = step.get("name") or None
        aid = step.get("automation_id") or None
        ct = step.get("control_type") or None
        combos = [
            (name, aid, ct),
            (name, None, ct),
            (name, aid, None),
            (name, None, None),
        ]
        for n, a, c in combos:
            if not (n or a):
                continue
            node, center = find_control({"uia_tree": tree}, name=n, automation_id=a, control_type=c)
            if center:
                return node, center
        return None, None
