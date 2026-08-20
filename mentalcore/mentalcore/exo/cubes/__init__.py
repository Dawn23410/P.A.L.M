"""外骨骼 6 个小魔方：工具/沙箱/计划/通信/记忆/安全。

每个魔方都是微内核，也是 Worker（WorkCore）内部的编排层级。
安全相关职责全部集中到安全魔方（SecurityCube）：
权限判定（工具魔方委托）+ 危险指令拦截（沙箱魔方委托）+ 提示注入/输出清洗 +
SSRF 防护 + 护栏规则（5 档 Profile + 规则引擎）+ 防幻觉/确认门 + 安全审计；
通信魔方仍负责 Worker 轨迹审计（TraceStore 后端）。
记忆魔方沿用已验证的 ProfessionalMemory（移植自 palm 双 Agent 资产）。
"""
from .tool_cube import ToolSpec, ToolDecision, ToolCube
from .sandbox_cube import SandboxCube, SandboxError
from .plan_cube import PlanCube, PlanStep
from .comm_cube import CommCube
from .security_cube import SecurityCube
from .guardrail import GuardRail, Rule, Condition, Profile
from .code_guard import guard_code, scan_code_risks, is_hard_blocked
from ..professional_memory import ProfessionalMemory, ProfessionalMemoryRecord

__all__ = [
    "ToolSpec", "ToolDecision", "ToolCube",
    "SandboxCube", "SandboxError",
    "PlanCube", "PlanStep",
    "CommCube",
    "SecurityCube",
    "GuardRail", "Rule", "Condition", "Profile",
    "guard_code", "scan_code_risks", "is_hard_blocked",
    "ProfessionalMemory", "ProfessionalMemoryRecord",
]
