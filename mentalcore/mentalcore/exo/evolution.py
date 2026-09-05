"""自主进化：技能注册 + 进化门 + 提示注入（移植自 palm/services/evolution/）。

- SkillRegistry：技能注册表（内存态，mock 零落盘）——技能 = 「被遵循的指导」，
  含状态治理（pending/approved/blocked/disabled），由宿主审批或自动通过。
- EvolutionGate：静态校验（浅层防御）——注入短语剥离 + 高风险关键词阻断 +
  长度/数量上限，防「固化错误套路」与提示注入。
- SkillInjector：把 approved 技能注入 Worker 提示（对齐归档 _injection 思路）。
"""
from __future__ import annotations

import hashlib
import re

# 高风险关键词：技能指导若含删除/格式化/提权/外联敏感，注册即拒（fail-closed 演示）
_HIGH_RISK_PATTERNS = (
    r"os\.remove|shutil\.rmtree|rm\s+-rf|del\s+/s|format\s+[a-z]:",
    r"os\.environ|getenv\([^)]*(KEY|TOKEN|SECRET|PASSWORD)",
    r"eval\(|exec\(|__import__|importlib",
    r"\.workbuddy|/etc/passwd|/etc/shadow|c:\\windows\\system32",
    r"删除\s*(全部|所有|一切)?\s*(文件|数据|资料)|格式化|清空\s*(磁盘|分区|硬盘|所有)",
    r"提权|绕过.*(安全|权限|闸门)|rootkit|挖矿|勒索",
)

# 注入短语剥离（对齐归档 _injection + 红队扩充）
_INJECTION_RE = re.compile(
    r"(?i)"
    r"(忽略(之前的|前述|以上|所有|上面)?(指令|提示|规则|系统提示|设定))"
    r"|(忘记(之前|前述|以上|上面)的(指令|提示|对话|设定))"
    r"|(disregard.{0,30}(previous|prior|above|all).{0,30}(instructions?|prompt|rules?|system))"
    r"|(ignore.{0,30}(previous|prior|above|all).{0,30}(instructions?|prompt|rules?|system))"
    r"|(system\s*prompt)"
    r"|(你(现在)?(必须|应该|需要)?(扮演|成为|模拟|假装))"
)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_BLOCKED = "blocked"
STATUS_DISABLED = "disabled"


class EvolutionGate:
    """进化门：技能文本静态校验（浅层防御，非主防线）。"""

    def __init__(self, max_content: int = 500, max_skills: int = 16):
        self.max_content = max_content
        self.max_skills = max_skills

    def sanitize(self, text: str) -> str:
        """剥离注入短语（注册与注入双保险）。"""
        return _INJECTION_RE.sub("", text or "")

    def high_risk_hit(self, text: str) -> str | None:
        """命中高风险模式返回命中描述，否则 None（拒绝注册）。"""
        low = (text or "").lower()
        for pat in _HIGH_RISK_PATTERNS:
            m = re.search(pat, low)
            if m:
                return f"技能含高风险模式：{m.group(0)[:40]}"
        return None


class Skill:
    """一条技能：指导文本 + 治理状态 + 来源哈希。"""

    def __init__(self, name: str, description: str, guidance: str,
                 source: str = "ai", status: str = STATUS_APPROVED):
        self.name = name
        self.description = description
        self.guidance = guidance
        self.source = source
        self.status = status
        self.digest = hashlib.sha256(guidance.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "guidance": self.guidance[:80], "source": self.source,
                "status": self.status, "digest": self.digest}


class SkillRegistry:
    """技能注册表：register 经进化门校验 → 状态治理 → 注入查询。"""

    def __init__(self, gate: EvolutionGate | None = None):
        self.gate = gate or EvolutionGate()
        self._skills: dict[str, Skill] = {}
        self.audit: list[dict] = []  # 治理审计（注册/阻断/审批）

    def register(self, name: str, description: str, guidance: str,
                 source: str = "ai", auto_approve: bool = True) -> tuple[bool, str]:
        """注册技能：净化 → 高风险阻断 → 数量上限 → 落表。"""
        name = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "_", str(name)[:40]).strip("_") or "skill"
        guidance = self.gate.sanitize(str(guidance)[: self.gate.max_content])
        description = self.gate.sanitize(str(description)[:120])
        if not guidance.strip():
            return False, "技能引导文本为空"
        risk = self.gate.high_risk_hit(guidance)
        if risk:
            self._audit("blocked", name, risk)
            return False, f"进化门拒绝：{risk}"
        if len(self._skills) >= self.gate.max_skills:
            self._audit("blocked", name, "技能数量超上限")
            return False, f"进化门拒绝：技能数量已达上限（{self.gate.max_skills}）"
        status = STATUS_APPROVED if auto_approve else STATUS_PENDING
        self._skills[name] = Skill(name, description, guidance, source, status)
        self._audit("registered" if status == STATUS_APPROVED else "pending", name, f"来源={source}")
        return True, f"技能已注册「{name}」（状态={status}）"

    def approve(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.status = STATUS_APPROVED
        self._audit("approved", name, "宿主审批通过")
        return True

    def disable(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.status = STATUS_DISABLED
        self._audit("disabled", name, "宿主停用")
        return True

    def approved(self) -> list[Skill]:
        return [s for s in self._skills.values() if s.status == STATUS_APPROVED]

    def list(self) -> list[dict]:
        return [s.to_dict() for s in self._skills.values()]

    def inject_text(self) -> str:
        """approved 技能 → 注入文本（供 Worker 提示拼接）。"""
        skills = self.approved()
        if not skills:
            return ""
        lines = ["【已习得技能】"]
        for s in skills:
            lines.append(f"- {s.name}：{s.description}。{s.guidance}")
        return "\n".join(lines)

    def _audit(self, action: str, name: str, detail: str) -> None:
        self.audit.append({"action": action, "name": name, "detail": detail})
