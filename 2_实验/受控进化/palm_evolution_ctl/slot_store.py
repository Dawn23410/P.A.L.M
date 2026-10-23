"""Phase 4 实现槽存储：AI 手搓硬件的完整生命周期管理。

安全铁律：AI 实现代码**绝不在主进程执行**——invoke 时把入参拼为 _SWAP_INPUT
全局变量，经 sandbox 砖 run_code_isolated 在隔离沙箱内执行实现代码（约定
`def entry(payload) -> dict`），结果由主进程拼接的 json.dumps 输出。

完整闭环（2026-08-06 完善）：
1. 人工授权开放插槽（swappable.json 持久化白名单，默认空 = 零开放）；
2. AI propose：黑名单硬拒 / 插槽已开放 → pending（可试运行、可激活）
   / 未开放 → pending_approval（进待授权队列，人工 approve 后开放并放行）；
3. dry_run 试运行（影子模式：沙箱跑一次，不注册不切换，可对比 primary）；
4. activate 激活（替换 capabilities 为实现槽，熔断失败自动回退 primary）；
5. deactivate 停用 / delete 删除。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from palm._core.paths import brick_local
from palm._core.container import CapabilitySlot, registry
from .gate import analyze, COVERAGE_BLACKLIST

_LOGGER = logging.getLogger(__name__)

# 运行时数据随砖内聚于 data/swaps/（git 忽略），砖可随意移动。
SWAPS_DIR = Path(brick_local(__file__, "data", "swaps"))
# 开放插槽白名单（持久化，人工授权）
_SWAPPABLE_FILE = SWAPS_DIR / "swappable.json"


# ── 开放插槽白名单（持久化） ──

def _load_slots() -> set[str]:
    try:
        if _SWAPPABLE_FILE.exists():
            return set(json.loads(_SWAPPABLE_FILE.read_text(encoding="utf-8")))
    except Exception as exc:
        _LOGGER.warning("插槽白名单加载失败，回退空集: %s", exc)
    return set()


def _save_slots(slots: set[str]) -> None:
    SWAPS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SWAPPABLE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(slots), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _SWAPPABLE_FILE)


def list_slots() -> list[dict]:
    """开放插槽清单（含砖/能力，供前端授权区展示）。"""
    return [{"slot": s, "brick": s.split(":", 1)[0], "capability": s.split(":", 1)[1]}
            for s in sorted(_load_slots())]


def is_slot_open(brick_name: str, cap_key: str) -> bool:
    return f"{brick_name}:{cap_key}" in _load_slots()


def open_slot(brick_name: str, cap_key: str) -> dict:
    """人工授权开放插槽（仅人工操作，AI 无此权限）。"""
    if brick_name in COVERAGE_BLACKLIST:
        return {"ok": False, "reason": f"{brick_name} 在覆盖黑名单（信任根死线），禁止开放"}
    slots = _load_slots()
    slots.add(f"{brick_name}:{cap_key}")
    _save_slots(slots)
    _append_audit("user", f"open {brick_name}:{cap_key}", "授权开放插槽", "mid", blocked=False)
    return {"ok": True}


def close_slot(brick_name: str, cap_key: str) -> dict:
    """收回插槽开放权限（不自动停用已激活实现，仅阻止新提交）。"""
    slots = _load_slots()
    slots.discard(f"{brick_name}:{cap_key}")
    _save_slots(slots)
    return {"ok": True}


# ── 实现包管理 ──

def _swap_dir(swap_id: str) -> Path:
    return SWAPS_DIR / swap_id


def _manifest_path(swap_id: str) -> Path:
    return _swap_dir(swap_id) / "manifest.json"


def _source_path(swap_id: str) -> Path:
    return _swap_dir(swap_id) / "impl.py"


def list_all() -> list[dict]:
    """列出全部实现包（含状态：pending_approval/pending/active/disabled/banned）。"""
    if not SWAPS_DIR.exists():
        return []
    result = []
    for d in sorted(SWAPS_DIR.iterdir()):
        mp = _manifest_path(d.name)
        if mp.exists():
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
                result.append(m)
            except Exception:
                continue
    return result


def get_swap(swap_id: str) -> dict | None:
    """实现包详情（含源码预览，不含完整代码以免前端载荷过大）。"""
    mp = _manifest_path(swap_id)
    if not mp.exists():
        return None
    m = json.loads(mp.read_text(encoding="utf-8"))
    code = _source_path(swap_id).read_text(encoding="utf-8")
    m["code"] = code
    m["code_preview"] = code[:400]
    return m


def _slot_for(brick_name: str, cap_key: str) -> CapabilitySlot | None:
    """取已注册的实现槽（未注册返回 None）。"""
    brick = container.get(brick_name)
    if brick is None:
        return None
    slot = brick.capabilities.get(cap_key)
    return slot if isinstance(slot, CapabilitySlot) else None


def propose(brick_name: str, cap_key: str, name: str, description: str,
            code: str, actor: str = "ai") -> dict:
    """提交实现包：黑名单硬拒 → gate 静态校验 → 落盘。

    插槽已开放 → status=pending（可试运行/激活）；未开放 → status=pending_approval
    （进待授权队列，人工 approve 后开放并放行）。
    """
    if brick_name in COVERAGE_BLACKLIST:
        _append_audit(actor, f"swap {brick_name}:{cap_key}", "覆盖黑名单", "high", blocked=True)
        return {"ok": False, "blocked": True,
                "reason": f"{brick_name} 在覆盖黑名单（信任根死线），禁止替换"}

    manifest = {"brick": brick_name, "capability": cap_key, "name": name,
                "description": description, "actor": actor,
                "status": "pending" if is_slot_open(brick_name, cap_key) else "pending_approval"}
    gate = analyze(code, manifest)
    if gate.blocked:
        _append_audit(actor, f"swap {brick_name}:{cap_key}", "; ".join(gate.findings),
                      gate.risk_level, blocked=True)
        return {"ok": False, "blocked": True, "reason": "; ".join(gate.findings),
                "risk_level": gate.risk_level}

    swap_id = f"{brick_name}_{cap_key}_{len(list_all()) + 1}"
    d = _swap_dir(swap_id)
    d.mkdir(parents=True, exist_ok=True)
    manifest["id"] = swap_id
    tmp = _manifest_path(swap_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _manifest_path(swap_id))
    _source_path(swap_id).write_text(code, encoding="utf-8")
    _append_audit(actor, swap_id, f"propose {brick_name}:{cap_key}", gate.risk_level, blocked=False)
    return {"ok": True, "id": swap_id, "status": manifest["status"],
            "needs_approval": manifest["status"] == "pending_approval"}


def approve(swap_id: str) -> dict:
    """人工审批实现包：开放对应插槽并将状态放行为 pending（可激活）。"""
    mp = _manifest_path(swap_id)
    if not mp.exists():
        return {"ok": False, "reason": "实现包不存在"}
    m = json.loads(mp.read_text(encoding="utf-8"))
    if m.get("status") == "banned":
        return {"ok": False, "reason": "该实现已被熔断拉黑"}
    open_slot(m["brick"], m["capability"])
    m["status"] = "pending"
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_audit("user", swap_id, "approve 授权开放并放行", "mid", blocked=False)
    return {"ok": True}


def _sandbox_caller(brick_name: str, cap_key: str, swap_id: str):
    """构造沙箱调用器：invoke 时经 sandbox 砖隔离执行实现代码。

    实现代码约定：定义 `def entry(payload) -> dict`（payload 为入参 dict）。
    入参以 _SWAP_INPUT 全局变量拼在实现代码前（不注入环境变量——避免触发
    gate 的 os.environ 敏感拦截），结果由主进程拼接的 json.dumps 输出。
    """
    code = _source_path(swap_id).read_text(encoding="utf-8")

    def caller(*args, **kwargs):
        sandbox_brick = container.get("sandbox")
        cap_fn = (sandbox_brick.capabilities.get("run_code_isolated")
                  if sandbox_brick else None)
        run_fn = cap_fn() if cap_fn else None
        if not run_fn:
            raise RuntimeError("沙箱砖未注册，AI 实现无法执行")
        payload = json.dumps({"args": list(args), "kwargs": kwargs}, ensure_ascii=False)
        runner = (
            f"_SWAP_INPUT = {payload}\n"
            f"{code}\n"
            "import json as _j\n"
            "print(_j.dumps(entry(_SWAP_INPUT), ensure_ascii=False))"
        )
        result = run_fn("python", runner, timeout=30, work_dir=str(_swap_dir(swap_id)))
        output = (result.get("output") or "").strip()
        if result.get("error"):
            raise RuntimeError("AI 实现执行出错: %s" % result["error"][:200])
        try:
            return json.loads(output) if output else None
        except json.JSONDecodeError:
            return output

    return caller


def dry_run(swap_id: str, sample_args: list = None, sample_kwargs: dict = None) -> dict:
    """影子模式试运行：沙箱跑一次实现（不注册不切换），返回结果供人工对比。

    sample_args 缺省时用空入参（entry 需容错）。
    """
    mp = _manifest_path(swap_id)
    if not mp.exists():
        return {"ok": False, "reason": "实现包不存在"}
    m = json.loads(mp.read_text(encoding="utf-8"))
    try:
        caller = _sandbox_caller(m["brick"], m["capability"], swap_id)
        result = caller(*(sample_args or []), **(sample_kwargs or {}))
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def activate(swap_id: str) -> dict:
    """激活实现包：注册到目标能力的实现槽并切换 active（熔断失败自动回退 primary）。"""
    mp = _manifest_path(swap_id)
    if not mp.exists():
        return {"ok": False, "reason": "实现包不存在"}
    m = json.loads(mp.read_text(encoding="utf-8"))
    if m.get("status") == "banned":
        return {"ok": False, "reason": "该实现已被熔断拉黑，禁止重新激活"}
    if m.get("status") == "pending_approval":
        return {"ok": False, "reason": "该实现待人工审批（插槽未开放），不能激活"}
    brick_name, cap_key = m["brick"], m["capability"]

    brick = container.get(brick_name)
    if brick is None or cap_key not in brick.capabilities:
        return {"ok": False, "reason": f"目标能力不存在：{brick_name}:{cap_key}"}

    slot = _slot_for(brick_name, cap_key)
    if slot is None:
        # 首次：用原能力作 primary 包装成实现槽并替换（调用方零改动，见 __call__）。
        slot = CapabilitySlot(brick.capabilities[cap_key])
        if not registry.swap_register(brick_name, cap_key, slot):
            return {"ok": False, "reason": "实现槽注册失败"}

    caller = _sandbox_caller(brick_name, cap_key, swap_id)
    slot.register(swap_id, caller)
    if not slot.activate(swap_id):
        return {"ok": False, "reason": "激活失败（可能已被拉黑）"}

    m["status"] = "active"
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_audit("ai", swap_id, "activate", "mid", blocked=False)
    return {"ok": True, "active": swap_id}


def deactivate(swap_id: str) -> dict:
    """停用实现包（回退 primary；不拉黑，可再激活）。"""
    mp = _manifest_path(swap_id)
    if not mp.exists():
        return {"ok": False, "reason": "实现包不存在"}
    m = json.loads(mp.read_text(encoding="utf-8"))
    slot = _slot_for(m["brick"], m["capability"])
    if slot is not None and slot.active_id == swap_id:
        slot.deactivate()
    m["status"] = "disabled"
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def delete_swap(swap_id: str) -> dict:
    """删除实现包（先停用再移除目录）。"""
    if not _manifest_path(swap_id).exists():
        return {"ok": False, "reason": "实现包不存在"}
    deactivate(swap_id)
    try:
        import shutil
        shutil.rmtree(_swap_dir(swap_id), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    _append_audit("user", swap_id, "delete 实现包", "low", blocked=False)
    return {"ok": True}


def _append_audit(actor: str, target: str, detail: str, risk: str, blocked: bool) -> None:
    """追加实现包审计（复用 registry.py 的审计文件）。"""
    try:
        from .registry import _append_audit as _ra
        _ra(actor, target, detail, risk, blocked)
    except Exception as exc:
        _LOGGER.warning("实现包审计写入失败: %s", exc)