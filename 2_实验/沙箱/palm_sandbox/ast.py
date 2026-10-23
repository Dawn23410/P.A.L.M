"""代码执行前静态分析接口（AST 预分析）。

为后续「提取代码中的网络地址或系统调用」预留可插拔接口。
- Python：使用标准库 ast 模块做真正的语法树遍历。
- Node/JS：标准库无 JS 解析器，使用启发式正则提取（接口一致，可后续替换为 esprima/acorn）。

analyze(lang, code) -> {
    "lang": str,
    "findings": [ {type, detail, line} , ... ],
    "hosts": [ "example.com", ... ],     # 提取到的潜在网络目标
    "risk": "low" | "medium" | "high",
}
"""
from __future__ import annotations

import ast
import re
from typing import Any

# 危险系统调用 / 网络 API 关键字（用于风险评分）
NET_CALLS = {
    "socket.socket", "socket.create_connection", "requests.get", "requests.post",
    "urllib.request.urlopen", "httpx.get", "aiohttp.ClientSession", "fetch",
    "net.connect", "http.get", "https.get", "axios",
}
DANGER_CALLS = {
    "os.system", "os.popen", "subprocess.run", "subprocess.Popen", "subprocess.call",
    "eval", "exec", "compile", "__import__", "ctypes", "os.remove", "shutil.rmtree",
    "os.chmod", "pickle.loads",
}

# 间接调用解析器（红蓝对抗 S2）：getattr/__getattribute__ 等可用于字符串拼接绕过
# 直接 Call 名检测（如 getattr(os, 'sys'+'tem')('rm -rf /')）。
_INDIRECT_RESOLVERS = {"getattr", "__getattribute__", "operator.attrgetter", "attrgetter"}

# 内建危险间接执行原语（直接调用即危险，无需属性链）
_DANGER_BUILTINS = {"eval", "exec", "__import__", "compile", "execfile", "reload"}


class CodeAnalyzer:
    """可插拔分析器基类。子类可 override analyze_* 实现真实解析。"""

    def analyze(self, lang: str, code: str) -> dict:
        lang = (lang or "").lower()
        if lang == "python":
            return self.analyze_python(code)
        if lang in ("node", "javascript", "js"):
            return self.analyze_js(code)
        return {"lang": lang, "findings": [], "hosts": [], "risk": "low"}

    # ---- Python：真实 AST ----
    def analyze_python(self, code: str) -> dict:
        findings: list[dict] = []
        hosts: set[str] = set()
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"lang": "python", "findings": [{"type": "syntax_error",
                    "detail": str(e), "line": getattr(e, "lineno", None)}],
                    "hosts": [], "risk": "low"}
        # 别名追踪（红蓝对抗 S2）：x = os.system / x = getattr(os,'system')
        # → 记录 x 指向的危险目标，后续 x(...) 调用命中。
        # Pass A: 收集字符串常量别名（t = 'sys'+'tem' → t→'system'），
        # 供后续 getattr(os, t) 还原属性名（红蓝对抗 S2 变量间接）。
        str_aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                lit = self._const_attr(node.value)
                if lit is not None:
                    str_aliases[node.targets[0].id] = lit
        # Pass B: 收集危险目标别名（x = os.system / f = getattr(os,'system') 等）
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                alias = self._resolve_alias_target(node.value, str_aliases)
                if alias is not None:
                    aliases[node.targets[0].id] = alias
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                # 1) 直接命中危险/网络调用
                if name in NET_CALLS:
                    findings.append({"type": "network_call", "detail": name,
                                     "line": node.lineno})
                    h = self._extract_host_from_args(node)
                    if h:
                        hosts.add(h)
                    continue
                if name in DANGER_CALLS:
                    findings.append({"type": "danger_call", "detail": name,
                                     "line": node.lineno})
                    continue
                # 2) 内建危险间接执行原语（eval(...) / __import__(...) 等）
                base = name.split(".")[-1] if name else ""
                if base in _DANGER_BUILTINS:
                    findings.append({"type": "danger_call",
                                     "detail": f"indirect:{name}", "line": node.lineno})
                    continue
                # 3) 间接解析器（getattr(os, 'sys'+'tem') → 还原目标并判定）
                if base in _INDIRECT_RESOLVERS:
                    resolved = self._resolve_getattr(node)
                    if resolved is not None and (resolved in DANGER_CALLS
                                                 or resolved in NET_CALLS):
                        ftype = "network_call" if resolved in NET_CALLS else "danger_call"
                        findings.append({"type": ftype,
                                         "detail": f"indirect:{resolved}", "line": node.lineno})
                        continue
                # 4) 别名调用（x(...) 且 x 指向危险目标）
                if name in aliases:
                    tgt = aliases[name]
                    ftype = "network_call" if tgt in NET_CALLS else "danger_call"
                    findings.append({"type": ftype,
                                     "detail": f"alias:{tgt}", "line": node.lineno})
                    continue
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in ("socket", "requests", "httpx",
                                                "aiohttp", "urllib", "subprocess", "os"):
                        findings.append({"type": "import", "detail": a.name,
                                         "line": node.lineno})
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] in ("socket", "requests", "httpx",
                                         "aiohttp", "urllib", "subprocess", "os"):
                    findings.append({"type": "import", "detail": mod,
                                     "line": node.lineno})
        # 字符串字面量里的 URL
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for h in self._urls_in_string(node.value):
                    hosts.add(h)
        risk = self._score(findings)
        return {"lang": "python", "findings": findings,
                "hosts": sorted(hosts), "risk": risk}

    # ---- JS/Node：启发式正则 ----
    def analyze_js(self, code: str) -> dict:
        findings: list[dict] = []
        hosts: set[str] = set()
        line_map = self._line_index(code)
        # 别名追踪（红蓝对抗 S3）：const f = eval / var g = Function → 后续 f(...)/g(...)
        # 标记为 danger_call。
        alias_re = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(eval|Function|require|child_process|execSync|exec|spawn)\b")
        aliases = set(alias_re.findall(code)) if False else \
            {m.group(1) for m in alias_re.finditer(code)}
        # 网络 API
        for pat, label in (
            (r"\brequire\(\s*['\"](https?://[^'\"]+)['\"]", "require_url"),
            (r"\b(fetch|axios|http\.get|https\.get|net\.connect)\s*\(", "network_call"),
            (r"\b(child_process|execSync|exec\(|spawn\()", "danger_call"),
            (r"\b(eval|Function\(|vm\.runInThisContext)\s*\(", "danger_call"),
        ):
            for m in re.finditer(pat, code):
                findings.append({"type": label, "detail": m.group(0)[:60],
                                 "line": line_map(m.start())})
        # 别名调用（f('...') 其中 f 是 eval/Function 别名）
        if aliases:
            for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(\s*(['\"])", code):
                if m.group(1) in aliases:
                    findings.append({"type": "danger_call",
                                     "detail": f"alias:{m.group(1)}(...)", "line": line_map(m.start())})
        for h in self._urls_in_string(code):
            hosts.add(h)
        risk = self._score(findings)
        return {"lang": "javascript", "findings": findings,
                "hosts": sorted(hosts), "risk": risk}

    # ---- 工具 ----
    @staticmethod
    def _call_name(func: ast.AST) -> str:
        if isinstance(func, ast.Attribute):
            base = func.value
            if isinstance(base, ast.Name):
                return "%s.%s" % (base.id, func.attr)
            if isinstance(base, ast.Attribute):
                return "%s.%s" % (CodeAnalyzer._call_name(base), func.attr)
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Subscript):
            # __builtins__['eval'](...) / globals()['os'](...) 下标调用
            vbase = func.value
            vname = vbase.id if isinstance(vbase, ast.Name) else ""
            key = CodeAnalyzer._const_attr(func.slice)
            if vname in ("__builtins__", "globals", "vars", "locals") and key:
                return key
        return ""

    @staticmethod
    def _resolve_alias_target(value: ast.AST,
                              str_aliases: dict[str, str] | None = None) -> str | None:
        """从赋值右侧还原危险目标名（os.system / getattr(os,'system') /
        getattr(os, t)（t 为字符串别名） / __import__ / __builtins__['eval'] 等）。"""
        if isinstance(value, ast.Attribute):
            full = CodeAnalyzer._call_name(value)
            return full if full in DANGER_CALLS or full in NET_CALLS else None
        if isinstance(value, ast.Name):
            return value.id if value.id in _DANGER_BUILTINS else None
        if isinstance(value, ast.Subscript):
            # f = __builtins__['eval'] / globals()['os']
            vbase = value.value
            vname = vbase.id if isinstance(vbase, ast.Name) else ""
            key = CodeAnalyzer._const_attr(value.slice)
            if vname in ("__builtins__", "globals", "vars", "locals") and key:
                if key in _DANGER_BUILTINS or key in DANGER_CALLS or key in NET_CALLS:
                    return key
            return None
        if isinstance(value, ast.Call):
            # getattr(os, 'system') / getattr(os, t) / __import__(...)
            base = CodeAnalyzer._call_name(value.func)
            if base in _INDIRECT_RESOLVERS and value.args:
                # 属性名：优先内联常量，其次变量别名（t='sys'+'tem'）
                target = CodeAnalyzer._const_attr(value.args[1]) if len(value.args) > 1 \
                    else CodeAnalyzer._const_attr(value.args[0])
                if not target and len(value.args) > 1 and str_aliases is not None \
                        and isinstance(value.args[1], ast.Name):
                    target = str_aliases.get(value.args[1].id)
                if target:
                    mod = CodeAnalyzer._call_name(value.args[0]) if value.args else ""
                    full = "%s.%s" % (mod, target) if mod else target
                    if full in DANGER_CALLS or full in NET_CALLS:
                        return full
            if base in _DANGER_BUILTINS:
                return base
        return None

    @staticmethod
    def _resolve_getattr(node: ast.Call) -> str | None:
        """从 getattr(os, 'sys'+'tem') 调用还原目标 os.system（拼接字符串也尝试还原）。"""
        if len(node.args) < 2:
            return None
        mod = CodeAnalyzer._call_name(node.args[0])
        attr = CodeAnalyzer._const_attr(node.args[1])
        if mod and attr:
            full = "%s.%s" % (mod, attr)
            if full in DANGER_CALLS or full in NET_CALLS:
                return full
            # 部分拼接（'sys'+'tem'）已合并为常量；若 attr 含 + 形式则退化为尝试
            if attr and (attr in DANGER_CALLS or attr in NET_CALLS):
                return attr
        return None

    @staticmethod
    def _const_attr(node: ast.AST) -> str | None:
        """提取常量字符串属性名（支持 'sys' / 'sys'+'tem' 拼接）。"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = CodeAnalyzer._const_attr(node.left)
            right = CodeAnalyzer._const_attr(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    @staticmethod
    def _extract_host_from_args(node: ast.Call) -> str | None:
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                m = re.match(r"https?://([^/:]+)", a.value)
                if m:
                    return m.group(1)
        return None

    @staticmethod
    def _urls_in_string(text: str) -> set[str]:
        out: set[str] = set()
        for m in re.finditer(r"https?://([A-Za-z0-9.\-]+)", text):
            out.add(m.group(1))
        return out

    @staticmethod
    def _line_index(code: str):
        lines = code.split("\n")
        cum = 0
        starts = []
        for ln in lines:
            starts.append(cum)
            cum += len(ln) + 1
        def find(pos: int) -> int:
            lo, hi = 0, len(starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if starts[mid] <= pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1
        return find

    @staticmethod
    def _score(findings: list[dict]) -> str:
        danger = sum(1 for f in findings if f["type"] == "danger_call")
        net = sum(1 for f in findings if f["type"] in ("network_call", "require_url"))
        # 同时具备「出网」与「危险系统调用」视为高危（如既外联又执行命令）
        if danger >= 1 and net >= 1:
            return "high"
        if danger >= 2 or net >= 3:
            return "high"
        if danger >= 1 or net >= 1:
            return "medium"
        return "low"


_DEFAULT = CodeAnalyzer()


# 截断阈值
_MAX_ANALYZE_CHARS = 200 * 1024    # 200 KB
_MAX_ANALYZE_LINES = 5000


def analyze(lang: str, code: str) -> dict:
    # 超长代码截断
    truncated = False
    truncated_note = ""
    if len(code) > _MAX_ANALYZE_CHARS:
        code = code[:_MAX_ANALYZE_CHARS]
        truncated = True
        truncated_note = "截断：超过 200KB"
    lines_count = code.count("\n") + 1
    if lines_count > _MAX_ANALYZE_LINES:
        code_lines = code.split("\n")[:_MAX_ANALYZE_LINES]
        code = "\n".join(code_lines)
        truncated = True
        truncated_note = "截断：超过 %d 行" % _MAX_ANALYZE_LINES
    result = _DEFAULT.analyze(lang, code)
    if truncated:
        result["truncated"] = True
        result["truncated_note"] = truncated_note
    return result
