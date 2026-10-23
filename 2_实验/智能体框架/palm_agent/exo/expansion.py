"""PCB 扩展板：AI 可插拔扩展槽位（EvolutionBoard）。

隐喻：一块 PCB 板，板上若干插槽（slot）。AI 经工具调用动态「插入」扩展——
技能（guidance 注入 Worker 提示）/ 提示片段 / 工具壳——插上的扩展立即生效，
拔除即失效。插槽数可配（防滥用），插入内容经进化门校验（注入清洗+高风险阻断）。

对外接口（既供 AI 经工具调用，也供宿主直接 API 调用）：
- plug(extension) / unplug(name) / list_extensions()
- register_skill(name, desc, guidance) → AI 自注册技能（高频用法）
- inject_into_prompt(goal) → 板上技能注入 Worker 提示
"""
from __future__ import annotations

from .evolution import EvolutionGate, SkillRegistry


class Extension:
    """一个可插拔扩展。kind: skill | prompt。"""

    def __init__(self, kind: str, name: str, description: str, content: str):
        self.kind = kind
        self.name = name
        self.description = description
        self.content = content

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name,
                "description": self.description, "content": self.content[:60]}


class ExpansionBoard:
    """PCB 扩展板：插槽管理 + 进化门 + 技能注入。"""

    def __init__(self, max_slots: int = 8, gate: EvolutionGate | None = None):
        self.max_slots = max_slots
        self.gate = gate or EvolutionGate()
        self.slots: dict[str, Extension] = {}
        # 技能经技能注册表管理（状态治理 + 注入文本）
        self.skills = SkillRegistry(self.gate)

    # ── 插槽管理 ──────────────────────────────────────────
    def plug(self, ext: Extension) -> tuple[bool, str]:
        """插入扩展：数量上限 + 内容净化 + 高风险阻断。"""
        if ext.name in self.slots:
            return False, f"插槽已占用：{ext.name}"
        if len(self.slots) >= self.max_slots:
            return False, f"扩展板槽位已满（{self.max_slots}）"
        content = self.gate.sanitize(ext.content)
        risk = self.gate.high_risk_hit(content)
        if risk:
            return False, f"进化门拒绝：{risk}"
        if ext.kind == "skill":
            ok, msg = self.skills.register(
                ext.name, ext.description, content, source="board")
            if not ok:
                return False, msg
        self.slots[ext.name] = Extension(ext.kind, ext.name,
                                         ext.description, content)
        return True, f"已插入扩展「{ext.name}」（kind={ext.kind}，槽位 {len(self.slots)}/{self.max_slots}）"

    def unplug(self, name: str) -> tuple[bool, str]:
        ext = self.slots.pop(name, None)
        if ext is None:
            return False, f"扩展不存在：{name}"
        self.skills.disable(name)  # 技能一并停用（保留治理记录）
        return True, f"已拔出扩展「{name}」"

    def list_extensions(self) -> list[dict]:
        return [e.to_dict() for e in self.slots.values()]

    # ── AI 自注册（工具封装入口）──────────────────────────
    def register_skill(self, name: str, description: str, guidance: str) -> str:
        ok, msg = self.plug(Extension("skill", name, description, guidance))
        return f"register_skill：{msg}"

    def inject_into_prompt(self, goal: str = "") -> str:
        """板上 approved 技能 → 注入文本（供 WorkCore._build_prompt 拼接）。"""
        return self.skills.inject_text()
