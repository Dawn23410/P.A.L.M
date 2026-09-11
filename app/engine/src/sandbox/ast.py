"""AI 沙箱 — 静态分析（AST 预分析）。

对即将执行的代码做静态扫描，识别危险模式（命令执行、网络外联、
文件系统破坏、权限提升等），为 guardrail 仲裁提供结构化信号。

接口契约（被 web.py /api/sandbox/analyze 调用）：
    analyze(lang: str, code: str) -> dict
"""

from __future__ import annotations

import ast as _ast
import re
from typing import Any, Dict, List

# 危险模式签名： (名称, 严重度, 匹配方式)
# 匹配方式可以是 python-ast 节点类型，或正则（用于非 python 语言）。
_DANGEROUS_CALLS = {
    "eval": ("code-injection", "high"),
    "exec": ("code-injection", "high"),
    "compile": ("code-injection", "medium"),
    "__import__": ("dynamic-import", "high"),
    "open": ("fs-access", "medium"),
    "os.system": ("command-exec", "high"),
    "os.popen": ("command-exec", "high"),
    "subprocess.Popen": ("command-exec", "high"),
    "subprocess.run": ("command-exec", "high"),
    "subprocess.call": ("command-exec", "high"),
    "shutil.rmtree": ("fs-destroy", "high"),
    "os.remove": ("fs-destroy", "medium"),
    "os.unlink": ("fs-destroy", "medium"),
    "socket.socket": ("network-egress", "medium"),
    "requests.get": ("network-egress", "medium"),
    "requests.post": ("network-egress", "medium"),
    "urllib.request": ("network-egress", "medium"),
    "pickle.loads": ("deserialization", "high"),
    "marshal.loads": ("deserialization", "high"),
    "ctypes": ("native-call", "high"),
    "os.chmod": ("permission-change", "medium"),
    "os.chown": ("permission-change", "medium"),
}

_NETWORK_SCHEME = re.compile(r"https?://|wss?://|ftp://", re.I)
_FS_DANGER = re.compile(r"rm\s+-rf|del\s+/[fqs]|format\s+[a-z]:", re.I)


def _scan_python(code: str) -> List[Dict[str, Any]]:
    """基于 Python AST 的安全扫描。"""
    hits: List[Dict[str, Any]] = []
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        return [{
            "pattern": "syntax-error",
            "severity": "info",
            "category": "parse",
            "detail": str(e),
            "line": getattr(e, "lineno", None),
        }]

    for node in _ast.walk(tree):
        # 直接调用危险内建
        if isinstance(node, _ast.Call):
            func = node.func
            name = ""
            if isinstance(func, _ast.Name):
                name = func.id
            elif isinstance(func, _ast.Attribute):
                name = func.attr
            if name in _DANGEROUS_CALLS:
                cat, sev = _DANGEROUS_CALLS[name]
                hits.append({
                    "pattern": name,
                    "severity": sev,
                    "category": cat,
                    "detail": "call %s()" % name,
                    "line": getattr(node, "lineno", None),
                })
        # import 危险模块
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            for alias in node.names:
                mod = alias.name
                if mod in ("os", "subprocess", "socket", "ctypes",
                           "shutil", "pickle", "marshal", "requests"):
                    cat, sev = _DANGEROUS_CALLS.get(
                        "os.system" if mod == "os" else mod, ("module-import", "medium"))
                    hits.append({
                        "pattern": "import:%s" % mod,
                        "severity": sev,
                        "category": "module-import",
                        "detail": "import %s" % mod,
                        "line": getattr(node, "lineno", None),
                    })
    return hits


def _scan_generic(code: str) -> List[Dict[str, Any]]:
    """非 Python 语言：基于正则的危险模式扫描。"""
    hits: List[Dict[str, Any]] = []
    for token, (cat, sev) in _DANGEROUS_CALLS.items():
        if "." in token:
            if re.search(r"\b" + re.escape(token) + r"\b", code):
                hits.append({
                    "pattern": token,
                    "severity": sev,
                    "category": cat,
                    "detail": "reference %s" % token,
                    "line": None,
                })
    if _NETWORK_SCHEME.search(code):
        hits.append({
            "pattern": "network-url",
            "severity": "medium",
            "category": "network-egress",
            "detail": "outbound url detected",
            "line": None,
        })
    if _FS_DANGER.search(code):
        hits.append({
            "pattern": "fs-destroy-cmd",
            "severity": "high",
            "category": "fs-destroy",
            "detail": "destructive filesystem command",
            "line": None,
        })
    return hits


def analyze(lang: str, code: str) -> Dict[str, Any]:
    """对代码做静态分析，返回结构化风险报告。

    返回字段（被 web.py 透传为 JSON）：
        risk       : "low" | "medium" | "high"
        score      : int (0-100，越高越危险)
        blocked    : bool (是否建议拦截)
        patterns   : List[dict] 命中的危险模式明细
        summary    : str 人类可读摘要
    """
    lang = (lang or "python").lower()
    if lang in ("py", "python", "python3"):
        patterns = _scan_python(code)
    else:
        patterns = _scan_generic(code)

    # 严重度加权
    weight = {"info": 0, "low": 5, "medium": 25, "high": 60}
    score = min(100, sum(weight.get(p.get("severity", "info"), 0) for p in patterns))
    if score >= 60:
        risk = "high"
    elif score >= 25:
        risk = "medium"
    else:
        risk = "low"

    blocked = score >= 60
    summary = "静态分析完成：命中 %d 项，风险等级 %s" % (len(patterns), risk)
    if not patterns:
        summary = "未检测到明显危险模式"

    return {
        "risk": risk,
        "score": score,
        "blocked": blocked,
        "patterns": patterns,
        "summary": summary,
        "lang": lang,
    }
