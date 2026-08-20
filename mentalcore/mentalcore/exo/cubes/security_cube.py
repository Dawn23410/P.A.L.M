"""安全魔方（微内核之一）：Agent 安全总闸——把涉及 Agent 的安全部分全部集中。

对应归档安全链 H1（提示注入）/M7（SSRF）+ exo 安全三拆分，统一入口：
- 权限判定：权限标签集合统一管理，工具调用前校验，越权即拒绝（fail-closed）。
- 提示注入清洗：工具入参/外部文本剔除高信号注入短语（H1，移植 _strip_prompt_injection）。
- 输出清洗：工具结果装饰壳剥离（复用 prompt._sanitize_tool_text）。
- SSRF 防护：网络目标主机校验，私有/环回/链路本地/保留/组播一律拒绝（M7，移植 _is_safe_host）。
- 危险指令拦截：统一危险命令黑名单（沙箱之外的第二道防线）。
- 安全审计：拒绝/拦截/清洗事件独立记录（不混入 Worker 轨迹，可单独查询）。
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from ..prompt import _sanitize_tool_text
from .guardrail import GuardRail, Rule

# 高信号提示注入短语（H1，移植 palm _native_execution._INJECTION_RE + 红队绕过补全）
_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|above|earlier|earlier\s+instructions)"
    r"\s*(instructions|prompts?|commands?)?"
    r"|disregard\s+(the\s+)?(above|previous|all\s+previous)"
    r"|forget\s+(the\s+)?(above|previous|all)\s+(instructions|prompts?|context)"
    r"|forget\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?|context)"
    r"|you\s+are\s+now\s+"
    r"|system\s+prompt\s*[:：]"
    r"|#+\s*instructions"
    r"|忽略\s*(所有|任何)?\s*(之前|上述|以上|前面|先前|全部)?\s*(的)?\s*(所有|任何)?\s*(指令|提示|要求|设定|规则|内容|指示)"
    r"|忘记(之前|上述|以上|前面|所有)的(指令|对话|设定|内容)"
    r"|(系统|开发者|开发者模式)\s*提示(词)?\s*[:：]"
    r"|开发者模式[:：]",
    re.IGNORECASE,
)

# 危险指令黑名单（沙箱执行前的纵深防御；Unix + Windows 命令，防绕过）
_DANGER_COMMANDS = (
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf ~/", "format ", "mkfs",
    "del /s", "del /f", "rd /s", "rmdir /s", "erase /s",
    "remove-item", "remove -item", "powershell", "pwsh",
    "diskpart", "format c:", "format d:", ":(){", "> /dev/sda", "dd if=",
    "bootsect", "bcdedit", "attrib -r -s -h c:", "cipher /w",
)

# 系统敏感路径（读写一律拦截——Worker 正常任务无需访问系统关键文件）
_SENSITIVE_PATHS = (
    "c:\\windows\\system32", "c:\\windows\\win.ini", "c:\\windows\\system.ini",
    "c:\\boot.ini", "c:\\pagefile.sys", "c:\\hiberfil.sys",
    "/etc/passwd", "/etc/shadow", "/etc/sudoers", "/root/",
)

# 默认放行权限（danger 恒不在内 → 危险操作必被权限闸门拒绝）
_DEFAULT_PERMISSIONS = [
    "fs_read", "fs_write", "web_read", "compute", "summarize", "shell", "ask",
    "gui",
]


class SecurityCube:
    """安全魔方：权限 / 清洗 / SSRF / 拦截 / 护栏规则 / 安全审计。"""

    def __init__(self, allowed_permissions: list | None = None,
                 profile: str = "strict", rules: list[Rule] | None = None,
                 rules_yaml: str | None = None):
        self._allowed = set(
            allowed_permissions if allowed_permissions is not None
            else list(_DEFAULT_PERMISSIONS))
        self.security_log: list[dict] = []  # 安全事件审计（拒绝/拦截/清洗）
        # 护栏规则引擎（方案1：5 档 Profile + 规则；默认 strict 兼容原 fail-closed）
        self.guardrail = GuardRail(profile, rules)
        if rules_yaml:
            self.guardrail.load_yaml(rules_yaml)

    # ── 权限判定 ──────────────────────────────────────────────
    def grant(self, permission: str) -> None:
        self._allowed.add(permission)

    def revoke(self, permission: str) -> None:
        self._allowed.discard(permission)

    def has_permission(self, permission: str) -> bool:
        return permission in self._allowed

    def check_permission(self, tool_name: str, requires: list) -> tuple[bool, str]:
        """工具调用前权限校验：越权即拒绝（fail-closed），并记安全事件。"""
        missing = [p for p in requires if p not in self._allowed]
        if missing:
            self._record("permission_deny", tool_name, f"需要权限 {missing} 未授权")
            return False, f"权限不足：需要 {missing}（当前未授权）"
        return True, "通过权限闸门"

    # ── 护栏裁决（GuardRail 委托）────────────────────────────
    def evaluate(self, tool_name: str, args: dict) -> str:
        """工具级精细裁决（权限闸门之后）：返回 allow/deny/warn/ask。"""
        return self.guardrail.evaluate(tool_name, args)

    def policies(self) -> list[dict]:
        """策略清单（对齐 GuardPort.policies，供管理与审计导出）。"""
        return self.guardrail.policies()

    def set_policy(self, policy: dict) -> None:
        """策略热更新（对齐 GuardPort.set_policy）。"""
        self.guardrail.set_policy(policy)

    def set_profile(self, profile: str) -> None:
        """运行时切换 5 档策略档位。"""
        self.guardrail.profile = GuardRail.profile_enum(profile)

    # ── 前置校验门（方案2：防幻觉/防误操作）──────────────────
    def check_grounding(self, tool_name: str, requires_grounding: bool,
                        verification_id: str | None) -> str | None:
        """防幻觉门：要求溯源核验的工具必须带 verification_id，否则拒绝。"""
        if requires_grounding and not verification_id:
            self._record("grounding_deny", tool_name,
                         "要求先经搜索/溯源核验并附带 verification_id")
            return ("拒绝：该操作要求先经搜索/溯源核验并附带 verification_id，"
                    "未提供则禁止执行（防幻觉误删/误发）。")
        return None

    def check_confirmation(self, tool_name: str, requires_confirmation: bool,
                           confirmed: bool | str | None) -> str | None:
        """确认门：高危操作需显式 confirmed=true（缺省拒绝，防误操作）。"""
        if requires_confirmation and not (
                confirmed is True or str(confirmed).lower() in ("1", "true", "yes")):
            self._record("confirm_deny", tool_name, "高风险操作未显式确认")
            return ("拒绝：该操作风险较高，请在参数中显式传入 confirmed=true 后再执行。")
        return None

    # ── 提示注入清洗（H1）─────────────────────────────────────
    def sanitize_input(self, text: str) -> str:
        """剔除工具入参/外部文本中的高信号注入短语（仅移除短语，避免误删合法内容）。"""
        return _INJECTION_RE.sub("", text or "")

    def sanitize_output(self, text: str) -> str:
        """工具结果清洗：剥离装饰壳 + 剔除注入短语（防恶意网页/文件内容回灌模型）。"""
        cleaned = _sanitize_tool_text(text)
        return _INJECTION_RE.sub("", cleaned or "")

    # ── SSRF 防护（M7）────────────────────────────────────────
    def assert_safe_host(self, url: str) -> None:
        """网络目标主机校验：私有/环回/链路本地/保留/组播地址一律拒绝。

        防绕过：进制 IP 字面量（0x/0o/0b）显式解析拒绝；解析结果为空即拒绝（fail-closed）。
        """
        host = urlparse(url).hostname
        if not host:
            raise RuntimeError("目标地址缺少主机名，已阻止（SSRF 防护）")
        candidates: set[str] = set()
        if host.replace(".", "").isdigit() or ":" in host:  # IP 字面量
            candidates.add(host)
        elif re.match(r"^0[xob]", host.lower()):  # 十六/八/二进制 IP（0x7f000001 等）
            try:
                ip = ipaddress.ip_address(int(host, 0))
                candidates.add(str(ip))
            except ValueError:
                raise RuntimeError("目标地址非法（进制 IP），已阻止（SSRF 防护）")
        else:
            try:
                infos = socket.getaddrinfo(host, None)
            except socket.gaierror:
                raise RuntimeError("目标主机无法解析，已阻止（SSRF 防护）")
            candidates.update(info[4][0] for info in infos)
        if not candidates:  # fail-closed：解析不出也拒绝（防 0x 形式被忽略放行）
            raise RuntimeError("目标主机无法解析，已阻止（SSRF 防护）")
        for ip_str in candidates:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                raise RuntimeError("目标地址非法，已阻止（SSRF 防护）")
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                self._record("ssrf_block", url, f"内网/保留地址 {ip_str}")
                raise RuntimeError(
                    f"目标地址为内网/保留地址 {ip_str}，已阻止（SSRF 防护）")

    # ── 危险指令拦截 ──────────────────────────────────────────
    def refuse_command(self, command: str) -> str | None:
        """命中危险指令黑名单返回拒绝文案，否则 None。

        空白归一（制表符/多空格→单空格）防绕过；另拦系统敏感路径读写（纵深防御）。
        """
        low = (command or "").lower()
        norm = re.sub(r"\s+", " ", low)
        # 分隔符归一：MSYS/CMD 会把 \ 转 /，且可能产生 // 连续斜杠——统一压成单斜杠再匹配
        norm_slash = re.sub(r"/+", "/", norm.replace("\\", "/"))
        for pat in _DANGER_COMMANDS:
            if pat in low or pat in norm or pat.replace("\\", "/") in norm_slash:
                self._record("danger_cmd", command[:80], f"命中 {pat!r}")
                return f"危险指令被安全魔方拦截：命中 {pat!r}"
        for sys_path in _SENSITIVE_PATHS:
            if (sys_path in low or sys_path in norm
                    or sys_path.replace("\\", "/") in norm_slash):
                self._record("sys_path_block", command[:80], f"系统敏感路径 {sys_path}")
                return f"系统敏感路径被安全魔方拦截：{sys_path}"
        return None

    # ── 安全审计 ──────────────────────────────────────────────
    def audit(self, kind: str, target: str, detail: str = "") -> None:
        """外部主动记一条安全事件（如工具执行结果清洗）。"""
        self._record(kind, target, detail)

    def _record(self, kind: str, target: str, detail: str) -> None:
        self.security_log.append({"kind": kind, "target": str(target)[:200],
                                  "detail": str(detail)[:300]})

    def get_audit(self) -> list[dict]:
        return list(self.security_log)
