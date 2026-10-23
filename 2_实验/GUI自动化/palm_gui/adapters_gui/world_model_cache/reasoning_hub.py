"""推理中枢：LLM 免费路线推断 + LLM 兜底 + 验证落盘学习闭环。

三级推断（详见 archive/docs/reasoning_hub_design.md）：
1. 路线记忆命中（path_memory）→ 直接复用，零 LLM；
2. 语义关键词推断（schema 能力标签 + Atlas 层级）→ 纯规则链控，零 LLM；
3. 不足 → 返回 needs_llm=True + 紧凑上下文，由上层调用 LLM 一次后 confirm_and_save 落盘。

本模块不耦合 agent/LLM 运行时——只产出结构化结果，保持可复用、可单测。
"""
from __future__ import annotations

import hashlib

from .registry import SoftwareRegistry
from .schema import _WORD_TO_CAPABILITY
from .path_memory import (record_route, query_route, record_exception,
                          intent_signature, _signature_overlap,
                          TRUST_HIGH, TRUST_MID, _TRUST_TRANSITION, _TRUST_COORD,
                          report_execution, get_route_stats)
from .transition_model import query_expected as _query_transition_expected
from .transition_model import get_transition_stats
from .coord_memory import get_coord as _get_coord, get_coord_stats

# 能力标签 → 执行动作（推理中枢把"语义控件"翻译为 run_automation 步骤）
_ACTION_BY_CAP = {
    "save": "click", "open": "click", "new": "click", "close": "click",
    "settings": "click", "delete": "click", "copy": "click", "paste": "click",
    "cut": "click", "find": "click", "undo": "click", "redo": "click",
    "back": "click", "next": "click", "confirm": "click", "cancel": "click",
    "print": "click", "export": "click", "import": "click", "help": "click",
    "refresh": "click", "play": "click", "pause": "click", "exit": "click",
    "select_all": "click", "bold": "click", "home": "click", "menu": "click",
    "toggle": "click", "navigate": "click",
}


def _level_struct_sig(level: dict) -> str:
    """层级结构签名（控件类型+静态名集合哈希）；软件更新导致布局变动时签名变化 → 路线失效。"""
    blobs: list[str] = []
    for n in level.get("nodes", []) or []:
        blobs.append(n.get("control_type", ""))
        nm = n.get("name", "") or ""
        if n.get("role") in ("static", None) and nm and len(nm) <= 20:
            blobs.append(nm)
    return hashlib.sha1("|".join(blobs).encode("utf-8")).hexdigest()[:10]


def _primary_level(levels: dict) -> dict:
    return levels.get("default") or next(iter(levels.values()))


def _current_struct_sig(software_id: str) -> str:
    entry = SoftwareRegistry().load(software_id)
    levels = entry.get("levels", {}) or {}
    return _level_struct_sig(_primary_level(levels)) if levels else ""


def _collect_capability_controls(entry: dict) -> list[dict]:
    """跨所有层级收集带能力标签的控件（推理中枢的"可寻址控件库"）。"""
    out: list[dict] = []
    for lv in (entry.get("levels", {}) or {}).values():
        lid = lv.get("level_id", "default")
        for n in lv.get("nodes", []) or []:
            caps = n.get("capability") or []
            if caps:
                out.append({
                    "level_id": lid,
                    "identity": n.get("identity"),
                    "name": n.get("name", ""),
                    "automation_id": n.get("automation_id", ""),
                    "control_type": n.get("control_type", ""),
                    "role": n.get("role", ""),
                    "capability": caps,
                })
    return out


def _intent_to_capabilities(intent: str) -> list[str]:
    """意图文本 → 期望能力标签（复用词库反向匹配；中文整词命中即可）。"""
    n = (intent or "").lower()
    caps: list[str] = []
    for w, cap in _WORD_TO_CAPABILITY.items():
        if w == n or w in n:
            if cap not in caps:
                caps.append(cap)
    return caps


def _score_control(control: dict, wanted_caps: list[str], intent_tokens: set[str]) -> int:
    """控件对意图的匹配分：能力命中×2 + 名称与意图词重叠（兼顾"关蓝牙"这类名词目标）。"""
    score = len(set(control["capability"]) & set(wanted_caps)) * 2
    nm = (control.get("name") or "").lower()
    if nm:
        for tok in intent_tokens:
            if len(tok) >= 2 and tok in nm:
                score += 1
    return score


def _match_controls(controls: list[dict], wanted_caps: list[str],
                    intent_tokens: set[str], top_k: int = 6) -> list[dict]:
    scored = [( _score_control(c, wanted_caps, intent_tokens), c) for c in controls]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def _build_steps(matched: list[dict]) -> list[dict]:
    """把匹配控件翻译为执行步骤（去重 identity，按匹配分降序）。"""
    seen: set[str] = set()
    steps: list[dict] = []
    for c in matched:
        if c["identity"] in seen:
            continue
        seen.add(c["identity"])
        action = _ACTION_BY_CAP.get((c["capability"] or ["click"])[0], "click")
        steps.append({
            "action": action,
            "name": c["name"],
            "automation_id": c["automation_id"],
            "control_type": c["control_type"],
            "action_label": "+".join(c["capability"]),
        })
    return steps


def _route_coord_keys(step: dict) -> list[str]:
    """候选坐标记忆键：兼容执行器(name|aid|ct|action)与转移规律层(ct|aid)两种格式。"""
    nm = step.get("name", "")
    aid = step.get("automation_id", "")
    ct = step.get("control_type", "")
    return [f"{nm}|{aid}|{ct}|click", f"{ct}|{aid or nm}"]


def _assess_linkage(software_id: str, steps: list[dict]) -> dict:
    """跨层联动佐证：路线步骤链是否被转移规律层支持、坐标记忆是否已覆盖。

    既为置信度提供增量信号（转移/坐标佐证→更可信），也为全局联动度审计产出原始指标。
    纯读取，不写任何记忆；缺失子系统时静默降级（coords=0 / transition_rate=0）。
    """
    trans_ok, trans_total = 0, 0
    coord_cov, coord_total = 0, 0
    for i, step in enumerate(steps):
        label = step.get("action_label") or (step.get("capability") or ["click"])[0]
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if nxt:
            trans_total += 1
            exp = _query_transition_expected(software_id, label, threshold=0.4, min_samples=2)
            keys = [k for k, _ in exp]
            nxt_aid = nxt.get("automation_id", "")
            nxt_nm = nxt.get("name", "")
            if any((nxt_aid and nxt_aid in k) or (nxt_nm and nxt_nm in k) for k in keys):
                trans_ok += 1
        coord_total += 1
        for ck in _route_coord_keys(step):
            if _get_coord(software_id, ck):
                coord_cov += 1
                break
    return {
        "transition_corroborated": trans_total > 0 and trans_ok == trans_total,
        "transition_rate": round(trans_ok / max(trans_total, 1), 2),
        "coord_coverage": round(coord_cov / max(coord_total, 1), 2),
    }


def _decide(confidence: float, stale: bool) -> str:
    """置信度→信任等级：trusted(纯推理) / verify(推理但校验) / weak(仍走 LLM)。

    stale（软件更新致结构过期）无论如何强制 verify，绝不盲信旧路线。
    """
    if stale:
        return "verify"
    if confidence >= TRUST_HIGH:
        return "trusted"
    if confidence >= TRUST_MID:
        return "verify"
    return "weak"


def _apply_decision(source: str, confidence: float, stale: bool, steps: list,
                    extra: dict) -> dict:
    """把信任等级翻译成 needs_llm / verify_after 决策，统一封装返回结构。

    关键适配（避免「记忆命中却因弱置信反复返 LLM」）：
    - weak 且已有候选 steps（memory/inferred 命中）→ 直接执行+校验，**不再浪费 LLM 重新规划**；
    - weak 且无候选 steps（真 llm_fallback）→ 才需调 LLM。
    这保证「越用越省」：首次 LLM 落盘后第 2 次即可免 LLM（执行+校验），直至 trusted 免校验。
    """
    trust = _decide(confidence, stale)
    has_steps = bool(steps)
    if trust == "trusted":
        needs_llm, verify_after = False, False
    elif trust == "verify":
        needs_llm, verify_after = False, True
    else:  # weak
        if has_steps:
            # 已有候选路线（历史成功/语义推断）→ 直接执行+校验，不重复消耗 LLM
            needs_llm, verify_after = False, True
        else:
            # 真正无任何候选 → 必须调 LLM 兜底
            needs_llm, verify_after = True, True
    return {"source": source, "needs_llm": needs_llm, "verify_after": verify_after,
            "trust": trust, "confidence": round(confidence, 3), "stale": stale,
            "steps": steps, "context": extra}


def infer_route(software_id: str, intent: str) -> dict:
    """推理中枢主入口：返回 {source, trust, needs_llm, verify_after, steps, confidence, stale, context}。

    source: "memory" | "inferred" | "llm_fallback"（零 LLM 优先，LLM 仅兜底）；
    trust:  "trusted"(纯推理直执行) | "verify"(推理但事后校验) | "weak"(仍走 LLM)；
    confidence: 渐进校准的置信度，衡量「到底第一次用 LLM 还是已可纯推理」——

      - 单次 LLM 落盘只给基线 0.12，首次再确认 0.26，远低于 MID(0.40)：
        绝不一次命中就全盘信任推理，必须先经校验或多次佐证；
      - 执行成功回写(+0.10)、转移/坐标联动佐证(+0.08/+0.06) 渐进抬升；
      - 越过 HIGH(0.80) 才纯推理直执行，达成「越用越准越快」的稳态。
    """
    sig = intent_signature(intent)
    if not sig:
        return {"source": "llm_fallback", "needs_llm": True, "verify_after": True,
                "trust": "weak", "steps": [], "confidence": 0.0,
                "context": {"reason": "空意图"}}
    entry = SoftwareRegistry().load(software_id)
    levels = entry.get("levels", {}) or {}
    # 当前结构签名（无 Atlas 时为空串，不阻断记忆命中，仅影响 stale 判定）
    cur_sig = _level_struct_sig(_primary_level(levels)) if levels else ""
    # 1) 路线记忆命中（最高优先，零 LLM；与 Atlas 是否建图无关——否则任何未建图软件
    #    永远走 LLM 兜底，打断「越用越准」。记忆是经验路线，本身不依赖结构认知）。
    mem = query_route(software_id, intent, cur_sig)
    if mem:
        steps = mem["steps"]
        conf = mem["confidence"]
        # 读取期佐证：转移/坐标联动越充分，可信度临时上浮（不写存储，仅影响本次决策）。
        link = _assess_linkage(software_id, steps)
        conf = min(1.0, conf + (_TRUST_TRANSITION if link["transition_corroborated"] else 0.0)
                   + link["coord_coverage"] * _TRUST_COORD)
        return _apply_decision("memory", conf, mem.get("stale", False), steps,
                               {"route_id": mem.get("route_id"), "samples": mem.get("samples"),
                                "linkage": link})
    # 2) 语义关键词推断（纯规则，零 LLM）——需 Atlas 控件库；无 Atlas 则跳过本路径
    if not levels:
        return {"source": "llm_fallback", "needs_llm": True, "verify_after": True,
                "trust": "weak", "steps": [], "confidence": 0.0,
                "context": {"reason": "Atlas 未建图且路径记忆未命中，本次走 LLM 兜底"}}
    wanted = _intent_to_capabilities(intent)
    controls = _collect_capability_controls(entry)
    matched = _match_controls(controls, wanted, sig)
    if matched:
        steps = _build_steps(matched)
        # 纯语义推断无执行证据，置信度封顶 0.45（永远落在 verify/weak 带），
        # 必须经执行校验或跨层佐证积累后才可能升入 trusted。
        conf = round(min(0.45, len(matched) / max(len(wanted), 1) * 0.45), 3)
        link = _assess_linkage(software_id, steps)
        conf = round(min(1.0, conf + (_TRUST_TRANSITION if link["transition_corroborated"] else 0.0)
                         + link["coord_coverage"] * _TRUST_COORD), 3)
        return _apply_decision("inferred", conf, False, steps,
                               {"matched": [m["name"] for m in matched],
                                "capabilities": wanted, "linkage": link})
    # 3) LLM 兜底（返回紧凑上下文，调用方调 LLM 一次后 confirm_and_save）
    avail = sorted({c for m in controls for c in m["capability"]})
    return {"source": "llm_fallback", "needs_llm": True, "verify_after": True,
            "trust": "weak", "steps": [], "confidence": 0.0,
            "context": {"reason": "无匹配路线/控件，需 LLM 规划",
                        "available_capabilities": avail}}


def confirm_and_save(software_id: str, intent: str, steps: list, success: bool,
                     source: str = "llm", exception_type: str = "",
                     recovered_steps: list | None = None) -> bool:
    """验证后落盘：LLM 规划+执行成功→存正常路线；曾纠正→存异常处理路线。"""
    if success:
        return record_route(software_id, intent, steps, outcome="ok",
                            source=source, structural_sig=_current_struct_sig(software_id))
    if recovered_steps:
        return record_exception(software_id, intent, steps, recovered_steps, exception_type)
    return False


def linkage_report(software_id: str) -> dict:
    """全局联动度审计：某软件四层子系统（Atlas/路线/转移/坐标）的覆盖与相互佐证程度。

    回答「各子系统是否真正联动」：不仅看各自有无数据，更看路线步骤链是否被转移规律层
    佐证、坐标记忆是否已覆盖可执行——联动度 = 子系统覆盖(60%) × 路线佐证率(40%)。
    缺失子系统时静默降级，分值随真实使用自然爬升（越用越联动）。
    """
    reg = SoftwareRegistry().load(software_id)
    has_atlas = bool(reg.get("levels"))
    rstats = get_route_stats(software_id)
    tstats = get_transition_stats(software_id)
    cstats = get_coord_stats(software_id)

    # 路线佐证率：每条正常路线的步骤链是否被转移规律层整体支持。
    corroborated, total = 0, 0
    for r in rstats.get("routes", []):
        if r.get("outcome") != "ok":
            continue
        link = _assess_linkage(software_id, r.get("steps", []))
        total += 1
        if link["transition_corroborated"]:
            corroborated += 1
    corr_rate = round(corroborated / max(total, 1), 2)

    subsystems = []
    if has_atlas:
        subsystems.append("atlas")
    if rstats.get("ok_routes", 0) > 0:
        subsystems.append("path_memory")
    if tstats.get("samples", 0) > 0:
        subsystems.append("transition")
    if cstats.get("coords", 0) > 0:
        subsystems.append("coord_memory")

    coverage = len(subsystems) / 4
    score = round(coverage * 0.6 + corr_rate * 0.4, 2)
    return {
        "software_id": software_id,
        "subsystems": subsystems,
        "has_atlas": has_atlas,
        "ok_routes": rstats.get("ok_routes", 0),
        "exceptions": rstats.get("exceptions", 0),
        "transition_samples": tstats.get("samples", 0),
        "coord_count": cstats.get("coords", 0),
        "corroboration_rate": corr_rate,
        "linkage_score": score,
    }
