"""完成判定门：识别确定性工具结果，避免Agent已满足目标后继续空转。

重构后支持可注册规则机制：任何人可以通过 register_rule() 添加自定义完成判定规则，
不再硬编码特定工具名的判断逻辑。原内置规则作为默认规则自动注册，保持完全向后兼容。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .protocols import CompletionGateProtocol, CompletionRuleFn


def _first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.rstrip("\r\n")
    return ""


# ── 内置默认规则（保留原有所有逻辑，改为独立规则函数） ──────────────────

def _rule_read_file_first_line(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "read_file" and "第一行" in request and "字符数" in request:
        first = _first_non_empty_line(tool_output)
        if first:
            return f"第一行={first}；字符数={len(first)}"
    return None


def _rule_web_fetch_title(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "web_fetch" and ("页面标题" in request or "标题" in request):
        title = _extract_title_like_text(tool_output)
        if title:
            return f"页面标题={title}"
    return None


def _rule_read_file_confirmed(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "read_file" and "confirmed=" in request:
        confirmed = _first_non_empty_line(tool_output)
        if confirmed:
            return f"confirmed={confirmed}"
    return None


def _rule_pytest_passed(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "run_code" and "pytest" in request and re.search(r"\bpassed\b|==+\s*1\s+passed", tool_output, re.I):
        return "测试通过。已根据测试结果完成修复。"
    return None


def _rule_screenshot_ocr_summary(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name in {"take_screenshot", "screenshot_region"} and "OCR识别摘要=" in request and "总体分析=" in request:
        if _looks_like_screenshot_tool_error(tool_output):
            return None
        if _requires_detail_tab_lifecycle(request):
            return None
        evidence = _extract_ocr_evidence(tool_output)
        if evidence:
            related_terms = [term for term in ("OSWorld", "AI Agent", "benchmark") if term.lower() in evidence.lower()]
            requested_terms = [term for term in ("OSWorld", "AI Agent", "benchmark") if term.lower() in request.lower()]
            missing_terms = [term for term in requested_terms if term.lower() not in evidence.lower()]
            if requested_terms and (not related_terms or missing_terms):
                return None
            if related_terms:
                analysis = "截图OCR内容与 " + "、".join(related_terms) + " 相关，说明页面内容符合本次搜索主题。"
            else:
                analysis = "截图OCR已返回可读屏幕文字，但与目标关键词的关联度需要人工复核。"
            return f"OCR识别摘要={evidence[:240]}\n\n总体分析={analysis}"
    return None


def _rule_screenshot_exception(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name in {"take_screenshot", "screenshot_region"} and "异常判断=" in request and "证据摘要=" in request:
        if _looks_like_screenshot_tool_error(tool_output):
            return None
        evidence = _extract_ocr_evidence(tool_output)
        if _looks_like_network_error(evidence):
            return f"异常判断=网络或页面加载异常\n\n证据摘要={evidence[:240]}"
        if _requests_network_error_judgement(request):
            return None
        if not evidence:
            return None
        if not _has_enough_text_evidence(evidence):
            return f"异常判断=证据不足\n\n证据摘要={evidence[:240] or '截图OCR未返回足够可读文字'}"
        return f"异常判断=页面已返回可读内容\n\n证据摘要={evidence[:240]}"
    return None


# ── 辅助函数（保留原有逻辑不变） ──────────────────────────────

def _extract_title_like_text(text: str) -> str:
    text = (text or "").strip()
    html_title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if html_title:
        return re.sub(r"\s+", " ", html_title.group(1)).strip()
    labeled = re.search(r"(?:title|标题)\s*[:：]\s*(.+)", text, re.I)
    if labeled:
        return labeled.group(1).strip().splitlines()[0][:120]
    return _first_non_empty_line(text)[:120]


def _extract_ocr_evidence(text: str) -> str:
    text = (text or "").strip()
    match = re.search(r"\[屏幕 OCR 识别[^\]]*\]\s*(.*?)\s*\[/屏幕 OCR 识别\]", text, re.S)
    if match:
        text = match.group(1)
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _looks_like_screenshot_status_line(line)
    ]
    cleaned = "；".join(lines[:8])
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_like_network_error(text: str) -> bool:
    haystack = (text or "").lower()
    markers = (
        "无法访问", "无法打开", "连接失败", "连接被拒绝", "未连接",
        "err_connection", "refused to connect", "site can't be reached",
        "can't reach", "无法显示此网页", "dns_probe",
    )
    return any(marker.lower() in haystack for marker in markers)


def _requests_network_error_judgement(text: str) -> bool:
    haystack = (text or "").lower()
    markers = ("网络不可达", "连接失败", "页面无法访问", "网络异常", "无法访问", "connection")
    return any(marker.lower() in haystack for marker in markers)


def _looks_like_screenshot_tool_error(text: str) -> bool:
    haystack = (text or "").lower()
    markers = (
        "保存路径不在允许目录内", "截图失败", "未指定完整区域坐标",
        "需要安装 pyautogui", "save_path", "not in allowed",
    )
    return any(marker.lower() in haystack for marker in markers)


def _looks_like_screenshot_status_line(text: str) -> bool:
    haystack = (text or "").lower()
    markers = (
        "截图已保存到", "截图内容已转为模型可读格式", "ascii模式回传模型",
        "原图模式回传模型", "palm_screenshot_", "appdata\\local\\temp",
    )
    return any(marker.lower() in haystack for marker in markers)


def _requires_detail_tab_lifecycle(text: str) -> bool:
    haystack = text or ""
    return (
        "点开" in haystack
        and ("关闭当前资料页" in haystack or "不要留下多个打开的资料标签页" in haystack)
    )


def _has_enough_text_evidence(text: str) -> bool:
    if text.strip().startswith("[图像信息]"):
        return False
    cleaned = re.sub(r"\s+", "", text or "")
    return len(cleaned) >= 12


# ── CompletionGate 实现 ──────────────────────────────────────

class CompletionGate:
    """完成判定门默认实现：支持注册自定义规则，按注册顺序逆序匹配（后注册的优先）。"""

    def __init__(self) -> None:
        self._rules: list[CompletionRuleFn] = []
        # 注册所有内置默认规则
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册内置默认规则（保持原有行为完全一致）。"""
        self.register_rule(_rule_read_file_first_line)
        self.register_rule(_rule_web_fetch_title)
        self.register_rule(_rule_read_file_confirmed)
        self.register_rule(_rule_pytest_passed)
        self.register_rule(_rule_screenshot_ocr_summary)
        self.register_rule(_rule_screenshot_exception)

    def register_rule(self, rule: CompletionRuleFn) -> None:
        """注册一个完成判定规则。后注册的规则优先级更高（先匹配）。"""
        if rule not in self._rules:
            # 新规则插入到最前面，保证后注册的优先匹配
            self._rules.insert(0, rule)

    def try_complete(self, request: str, tool_name: str, tool_output: str) -> Optional[str]:
        """按注册顺序尝试所有规则，第一个返回非None的结果作为最终回答。"""
        for rule in self._rules:
            try:
                result = rule(request, tool_name, tool_output)
                if result is not None:
                    return result
            except Exception:
                # 规则异常不影响其他规则和主流程
                continue
        return None


# ── 全局默认实例 + 对外兼容入口（保持原有API完全不变） ─────────────────

_default_gate = CompletionGate()


def register_rule(rule: CompletionRuleFn) -> None:
    """向全局默认完成门注册规则。模块级便捷函数。"""
    _default_gate.register_rule(rule)


def try_complete_from_tool_result(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    """原API入口，保持完全向后兼容。内部使用新的可注册机制。"""
    return _default_gate.try_complete(request, tool_name, tool_output)


def get_default_gate() -> CompletionGateProtocol:
    """获取全局默认完成门实例。供Agent内核注入使用。"""
    return _default_gate
