"""SelfEvolutionGate：自注册工具的静态校验（浅层防御，非主防线）。

校验层次：
1. AST 导入白名单（确定性，拦住绝大多数越权 import）；
2. 危险原语（importlib/compile/eval/exec/__import__）直接阻断；
3. entry 函数存在性；
4. 破坏性操作 / 外联 / 敏感内容 / 路径穿越 检测（正则，标 risk 或阻断）。

注意：白名单可被 importlib.import_module / compile 绕过，真边界是隔离账户；
本 Gate 只挡"无心之失与明显恶意"，高敏仍需人审。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

ALLOWED_IMPORTS = {
    "pathlib", "re", "json", "math", "datetime", "typing", "collections",
    "itertools", "functools", "random", "string", "hashlib", "base64",
    "textwrap", "dataclasses", "time",
}

DANGEROUS_BUILTINS = {"importlib", "compile", "eval", "exec", "__import__"}

DESTRUCTIVE_PATTERNS = [
    r"\bos\.remove\b", r"\bos\.unlink\b", r"\bos\.rmdir\b", r"\bshutil\.rmtree\b",
    r"\bshutil\.move\b", r"\bos\.replace\b",
    r"\bpathlib\.Path\([^)]*\)\.unlink\b", r"\bpathlib\.Path\([^)]*\)\.rmdir\b",
    r"open\([^)]*,\s*['\"](?:w|a|x)['\"]",
]

NETWORK_IMPORTS = {
    "socket", "requests", "urllib", "httpx", "aiohttp",
    "websocket", "ftplib", "smtplib",
}

SENSITIVE_PATTERNS = [
    r"\bcrypto\b", r"os\.environ", r"getenv\([^)]*?(?:KEY|TOKEN|SECRET|PASSWORD)",
    r"\.workbuddy",
]

_RANK = {"low": 0, "mid": 1, "high": 2}


def _max_risk(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass
class GateResult:
    blocked: bool
    risk_level: str
    findings: list[str]
    has_destructive: bool


def analyze(source: str, manifest: dict) -> GateResult:
    """静态分析工具源码，返回是否阻断、风险等级、发现项。"""
    findings: list[str] = []
    risk = "low"
    blocked = False
    has_destructive = False
    declared_imports = set(manifest.get("imports_allowlist") or [])

    try:
        tree = ast.parse(source)
    except SyntaxError as err:
        return GateResult(True, "high", [f"语法错误：{err}"], False)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in DANGEROUS_BUILTINS:
                    findings.append(f"禁止的动态导入原语：{top}")
                    blocked = True
                    risk = _max_risk(risk, "high")
                elif top not in ALLOWED_IMPORTS and top not in declared_imports:
                    findings.append(f"非白名单导入：{alias.name}")
                    blocked = True
                    risk = _max_risk(risk, "high")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in DANGEROUS_BUILTINS:
                findings.append(f"禁止的 from 导入：{top}")
                blocked = True
                risk = _max_risk(risk, "high")
            elif top not in ALLOWED_IMPORTS and top not in declared_imports:
                findings.append(f"非白名单 from 导入：{node.module}")
                blocked = True
                risk = _max_risk(risk, "high")

    if not re.search(r"def\s+entry\s*\(", source):
        findings.append("缺少 entry 函数定义")
        blocked = True
        risk = _max_risk(risk, "high")

    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, source):
            findings.append(f"检测到破坏性操作：{pattern[:24]}")
            has_destructive = True
            risk = _max_risk(risk, "high")

    net_declared = manifest.get("requires_network") is True
    for module in NETWORK_IMPORTS:
        if re.search(rf"\b{module}\b", source):
            if not net_declared:
                findings.append(f"未声明的外联模块：{module}")
                blocked = True
                risk = _max_risk(risk, "high")
            else:
                findings.append(f"外联模块（已声明）：{module}")
                risk = _max_risk(risk, "mid")

    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, source, re.IGNORECASE):
            findings.append(f"敏感内容命中：{pattern}")
            risk = _max_risk(risk, "high")

    if ".." in source and not manifest.get("allow_path_traversal"):
        findings.append("疑似路径穿越（..）")
        risk = _max_risk(risk, "high")

    return GateResult(blocked, risk, findings, has_destructive)


# 技能是"被遵循的指令"，治理重点是正确性：禁止内含绕过权限 / 静默越权 / 改源码等指令。
SKILL_FORBIDDEN_PATTERNS = [
    r"绕过权限", r"绕过守卫", r"静默越权", r"禁用安全", r"关闭安全",
    r"跳过鉴权", r"忽略安全", r"绕过\s*安全",
    r"bypass\s+(?:permission|guard|safety|security)",
    r"disable\s+(?:safety|security|guard)",
    r"修改源码", r"改源码", r"源码级自改", r"sys\.modules", r"importlib\.reload",
    r"静默删除", r"绕过删除确认",
]


def scan_skill_content(content: str) -> GateResult:
    """静态扫描凝聚出的技能正文，阻断"绕过安全 / 改源码"类指令。"""
    findings: list[str] = []
    risk = "low"
    blocked = False

    for pattern in SKILL_FORBIDDEN_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            findings.append(f"技能含禁止指令（疑似绕过安全/改源码）：{pattern}")
            blocked = True
            risk = _max_risk(risk, "high")

    # 疑似数据外发仅提醒、不阻断，交由人审判定（技能本身可能是合法导出流程）。
    if re.search(r"外联|上传|exfiltrat|外发|打包发送", content, re.IGNORECASE):
        findings.append("技能描述疑似涉及数据外发，需人审确认")
        risk = _max_risk(risk, "high")

    return GateResult(blocked, risk, findings, False)


# ---- Phase 4 覆盖声明校验（AI 手搓硬件） ----

# 覆盖黑名单：AI 永远不可替换的插槽（信任根死线之一）。
COVERAGE_BLACKLIST = {"gate", "safety", "sandbox", "registry", "agent"}

# swappable 白名单：默认零开放，逐槽人工授权后在此添加（"brick_name:cap_key"）。
SWAPPABLE_SLOTS: set[str] = set()


def validate_swap_declaration(brick_name: str, cap_key: str) -> tuple[bool, str]:
    """校验 AI 手搓硬件的覆盖声明。

    返回 (通过, 原因)。黑名单硬拒；白名单默认空 → 默认拒绝一切覆盖（安全默认）。
    """
    if brick_name in COVERAGE_BLACKLIST:
        return False, f"{brick_name} 在覆盖黑名单中（信任根死线），禁止替换"
    slot_key = f"{brick_name}:{cap_key}"
    if slot_key not in SWAPPABLE_SLOTS:
        return False, f"插槽 {slot_key} 未开放替换（swappable 白名单为空，默认零开放）"
    return True, "ok"
