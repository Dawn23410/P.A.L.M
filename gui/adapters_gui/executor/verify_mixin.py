"""鲁棒性/预测校验 mixin：点击后预测控件轮询、转移规律记录（无 OCR）。"""
import time

from ..world_model import build_uia_tree, find_control
from ..world_model_cache.transition_model import (
    query_expected, record_transition, _NOISE_CT, _NOISE_NAME, _control_key)
from .constants import _LOGGER


class _VerifyMixin:
    """点击后的廉价校验：预测控件轮询出现，处理界面重绘延迟，维持转移规律库生长。"""

    def _normalize_identifiers(self, raw: list) -> list[dict]:
        """统一控件标识符：字符串→按名匹配；'ct|aid' 转移键→ct+aid 双匹配；dict→原样。"""
        out = []
        for r in raw:
            if isinstance(r, dict):
                out.append(r)
            elif isinstance(r, str):
                if "|" in r:
                    ct, aid = r.split("|", 1)
                    out.append({"control_type": ct, "automation_id": aid, "name": aid})
                else:
                    out.append({"name": r})
        return out

    def _verify_controls_uia(self, hwnd: int, idents: list[dict]) -> dict:
        """廉价校验一组控件在实时 UIA 树中存在（~10ms/个，不碰 OCR）。"""
        try:
            tree = build_uia_tree(hwnd)
        except Exception as exc:
            return {"present": [], "missing": idents, "error": str(exc)}
        present, missing = [], []
        for ident in idents:
            node, _ = find_control({"uia_tree": tree},
                                   name=ident.get("name") or None,
                                   automation_id=ident.get("automation_id") or None,
                                   control_type=ident.get("control_type") or None)
            (present if node else missing).append(ident)
        return {"present": present, "missing": missing}

    def _poll_predicted(self, hwnd: int, idents: list[dict], timeout_s: float) -> dict:
        """点击后轮询预测控件出现（吸收界面重绘延迟）；命中全部或超时退出。
        相比点击后立即判成功，此机制避免 UI 滞后导致的误报失败与后续 LLM 复查。"""
        if not idents:
            return {"present": [], "missing": []}
        deadline = time.perf_counter() + max(0.0, min(timeout_s, 3.0))
        last = {"present": [], "missing": idents}
        while time.perf_counter() < deadline:
            last = self._verify_controls_uia(hwnd, idents)
            if not last.get("missing"):
                break
            time.sleep(0.15)
        return last

    def _tree_control_keys(self, tree: dict) -> set:
        """从 UIA 树抽取去噪控件标识集合（复用转移层噪声表，避免跨模块耦合）。"""
        keys: set = set()

        def walk(n):
            if isinstance(n, dict):
                name = (n.get("name") or "").strip()
                aid = n.get("automation_id") or ""
                ct = n.get("control_type") or ""
                if (name or aid) and n.get("visible") and ct not in _NOISE_CT and name not in _NOISE_NAME:
                    k = _control_key(ct, aid, name)
                    if k:
                        keys.add(k)
                for ch in n.get("children", []) or []:
                    walk(ch)
        walk(tree)
        return keys

    def _record_transition_after(self, hwnd: int, sid: str, label: str) -> None:
        """点击后廉价 UIA 树抽取控件集合记入转移规律层（无 OCR）。
        维持预测 DB 在 LLM 减少 describe_window 调用时仍持续生长。"""
        try:
            tree = build_uia_tree(hwnd)
            keys = self._tree_control_keys(tree.get("tree", {}))
            if keys:
                record_transition(sid, label, keys)
        except Exception as exc:
            _LOGGER.warning("转移规律记录失败(hwnd=%s): %s", hwnd, exc)

    def _verify_after_click(self, step: dict, hwnd: int) -> str:
        """点击后用预测的预期控件做轻量校验（轮询出现，处理重绘延迟）。
        显式 expect 优先；无则查转移规律层高置信预测。命中则 LLM 可跳过 describe_window 复查。"""
        entry = self._cache.get(hwnd, {})
        sid = self._sid(hwnd)
        raw = list(step.get("expect") or [])
        label = step.get("action_label") or (step.get("name") or step.get("automation_id") or "")
        if not raw and sid and label:
            try:
                raw = [k for k, _ in query_expected(sid, label, threshold=0.8)]
            except Exception:
                raw = []
        if not raw:
            return ""
        idents = self._normalize_identifiers(raw)
        res = self._poll_predicted(hwnd, idents, step.get("verify_timeout", 1.0))
        missing = len(res.get("missing", []))
        # 命中预测即记录本次转移，维持 DB 增长（即便 LLM 不再调 describe_window）
        if sid and label:
            self._record_transition_after(hwnd, sid, label)
        if missing == 0:
            return f"预测控件全部出现({len(idents)}个)"
        return f"预测控件缺失 {missing}/{len(idents)} 个"
