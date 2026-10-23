"""Agent 提示构建与角色语气清洗（Mixin，由 Agent 继承）。

重构后所有角色扮演逻辑通过 self.persona_provider 访问，工具匹配通过 self._matcher 访问，
不再硬编码依赖全局函数，支持注入自定义实现。
"""
from __future__ import annotations

import logging
import os
import re
import socket
import platform
import time
from datetime import datetime

from .prompt_templates import (
    SYSTEM_PROMPT_TPL,
    DEEP_THINK_INSTRUCTION,
)
from .native_runner import _sanitize_tool_text

_LOGGER = logging.getLogger(__name__)

# 预加载总时长硬上限（毫秒），超时仅告警不阻断
_PRELOAD_BUDGET_MS = 350


class PromptMixin:
    """组装 system prompt、构建历史、预加载语义上下文、清洗角色语气。"""

    def _strip_roleplay_tone(self, text: str) -> str:
        """非角色扮演模式下，过滤文本里的角色化表达残留。"""
        known_names = self.persona_provider.collect_known_character_names()
        return self.persona_provider.strip_roleplay_tone(text, known_names)

    def _collect_known_character_names(self) -> list[str]:
        """返回当前进程已加载的全部角色名——委托给persona_provider。"""
        return self.persona_provider.collect_known_character_names()

    def _clean_assistant_text(self, text: str) -> str:
        """无角色扮演时清洗助手文本里的角色化残留。"""
        return self.persona_provider.clean_assistant_text(text, bool(self._persona_text))

    def _build_history(self) -> str:
        """从记忆中构建对话历史文本（仅最近 10 轮，避免旧话题干扰）。"""
        ctx = self._memory.get_context()
        recent = ctx[-20:] if len(ctx) > 20 else ctx
        lines = []
        for msg in recent:
            role = msg["role"]
            content = msg["content"][:500]
            if role == "assistant" and not self._persona_text:
                content = self._strip_roleplay_tone(_sanitize_tool_text(content))
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "(空)"

    def _build_prompt(self, force_text_hint: str | None = None) -> list[dict]:
        """组装 system prompt + 语义匹配的工具推荐。"""
        history = self._build_history()
        memory_context = _sanitize_tool_text(self._memory.inject_system_context())
        if not self._persona_text:
            memory_context = self._strip_roleplay_tone(memory_context)
        # 预加载的 Observation
        if self._preloaded_observations:
            obs_text = "\n".join(self._preloaded_observations)
            memory_context = (
                memory_context + "\n\n## 预加载信息（请以此为准）\n" + obs_text
                if memory_context else "## 预加载信息\n" + obs_text
            )
        roleplay_section = self._compile_roleplay_section()
        prompt_tools, total = self._select_prompt_tools()
        tools_prompt_lines = self._render_tools_prompt_lines(prompt_tools)
        tool_search_note = (
            f"💡 以上仅列出部分推荐工具。系统共 {total} 个工具，"
            f"如需搜索全部工具请调用 search_tools 查找。"
        )
        sys_prompt = SYSTEM_PROMPT_TPL.format(
            roleplay_context=roleplay_section or "",
            history=history,
            memory_context=memory_context,
            deep_think_instruction=DEEP_THINK_INSTRUCTION if self._deep_think else "",
            total=total,
        )
        # 无角色时追加强约束
        if not self._persona_text:
            sys_prompt += self.persona_provider.get_no_roleplay_constraint()
        # 强制收尾指令
        if force_text_hint:
            sys_prompt += "\n\n" + force_text_hint
        # 用户情绪感知提示
        emotion_hint = getattr(self, "_emotion_hint", "") or ""
        if emotion_hint:
            sys_prompt += emotion_hint
        return [{"role": "system", "content": sys_prompt}]

    def _compile_roleplay_section(self) -> str:
        """构建角色设定段落——完全委托给persona_provider。"""
        return self.persona_provider.compile_roleplay_section(self._memory, self._user_message)

    def _select_prompt_tools(self) -> tuple[list, int]:
        """按语义匹配筛选相关工具，使用注入的self._matcher。"""
        all_tools = self._list_available_tools()
        # 角色扮演场景下跳过排名
        if self.persona_provider.should_filter_tools():
            ranked_names = {"search_tools"}
        elif self._auto_filter_tools:
            ranked = self._matcher.rank(self._user_message, top_k=20)
            ranked_names = {r[0] for r in ranked}
        else:
            ranked_names = {t.spec.name for t in all_tools}
        # 强制保留通用基础工具
        ALWAYS_INCLUDE = {
            "run_code", "search_tools", "take_screenshot", "hotkey",
            "press_key", "type_text", "click_mouse", "write_file",
            "read_file", "web_search", "web_fetch", "ask_user",
        }
        pinned = [t for t in all_tools if t.spec.name in ALWAYS_INCLUDE]
        matched = [t for t in all_tools if t.spec.name in ranked_names]
        fallback = [
            t for t in all_tools
            if t.spec.name not in ranked_names and t.spec.name not in ALWAYS_INCLUDE
        ][:5]
        return pinned + matched + fallback, len(all_tools)

    def _render_tools_prompt_lines(self, prompt_tools: list) -> list[str]:
        """去重后生成工具的 prompt 文本行。"""
        seen = set()
        lines = []
        for tool in prompt_tools:
            if tool.spec.name in seen:
                continue
            seen.add(tool.spec.name)
            lines.append(tool.to_react_prompt())
        return lines

    def _preload_context(self, message: str) -> None:
        """语义预加载：关键词匹配前置激活工具，结果以 Observation 注入 context。"""
        t0 = time.time()
        msg_lower = message.lower()
        preloads = self._collect_time_observations(msg_lower)
        preloads += self._collect_system_observations(msg_lower)
        self._preloaded_observations = preloads if preloads else []
        elapsed = (time.time() - t0) * 1000
        if elapsed > _PRELOAD_BUDGET_MS:
            _LOGGER.warning("上下文预加载超时 %.0fms（上限 %dms）", elapsed, _PRELOAD_BUDGET_MS)

    def _collect_time_observations(self, msg_lower: str) -> list[str]:
        """命中时间/日期/时区关键词时，本地计算当前时间与时区。"""
        keywords = [
            "时间", "日期", "今天", "昨天", "明天", "星期", "几号", "几月", "几几年",
            "现在", "几点", "time", "date", "today", "tomorrow", "yesterday",
            "时区", "时差", "timezone", "utc", "gmt",
        ]
        if not any(kw in msg_lower for kw in keywords):
            return []
        now = datetime.now()
        tz_name = time.tzname[0]
        utc_offset = -time.timezone // 3600
        sign = "+" if utc_offset >= 0 else ""
        return [
            "Observation: get_datetime -> " + now.strftime("%Y-%m-%d %H:%M:%S %A")
            + f"（时区 {tz_name} UTC{sign}{utc_offset}）",
            "Observation: get_timezone -> " + tz_name + f" UTC{sign}{utc_offset}",
        ]

    def _collect_system_observations(self, msg_lower: str) -> list[str]:
        """命中系统/主机关键词时，本地取主机名、系统、架构、用户名。"""
        keywords = [
            "系统", "电脑", "操作系统", "os", "system", "platform", "本机", "配置",
            "cpu", "gpu", "内存", "硬盘", "用户", "用户名", "hostname", "主机名",
        ]
        if not any(kw in msg_lower for kw in keywords):
            return []
        host = socket.gethostname()
        system = platform.system() + " " + platform.release()
        arch = platform.machine()
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        return [f"Observation: get_system_info -> 主机 {host}，系统 {system}，架构 {arch}，用户 {user}"]
