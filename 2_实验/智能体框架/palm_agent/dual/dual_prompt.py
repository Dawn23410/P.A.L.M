"""Agent 提示构建与角色语气清洗（Mixin，由 Agent 继承）。

仅承载与「system prompt 组装 / 对话历史 / 上下文预加载 / 角色语气清洗」相关的
方法，使 Agent 主类保持精简、单一职责。
"""
from __future__ import annotations

import logging
import os
import re
import socket
import platform
import time
from datetime import datetime

from ..prompt_templates import (
    SYSTEM_PROMPT_TPL,
    DEEP_THINK_INSTRUCTION,
)
from .dual_runner import _sanitize_tool_text
from ..tool_matcher import get_matcher
from palm._core.interop import get_roleplay_api

_LOGGER = logging.getLogger(__name__)


def _roleplay_api():
    # 角色扮演砖门面：strip_roleplay_tone / list_characters / _NO_ROLEPLAY_CONSTRAINT 等经 capability 取用。
    api = get_roleplay_api()
    if api is None:
        raise RuntimeError("角色扮演砖未注册")
    return api

# 预加载总时长硬上限（毫秒），超时仅告警不阻断
_PRELOAD_BUDGET_MS = 350


class PromptMixin:
    """组装 system prompt、构建历史、预加载语义上下文、清洗角色语气。"""

    def _strip_roleplay_tone(self, text: str) -> str:
        """非角色扮演模式下，过滤文本里的角色化表达残留，委托共享实现（含动态角色名）。"""
        return _roleplay_api().strip_roleplay_tone(text, self._collect_known_character_names())

    def _collect_known_character_names(self) -> list[str]:
        """返回当前进程已加载的全部角色名（内置+用户导入）。

        缓存避免 strip 热路径重复扫盘；新增/导入角色后通过 invalidate_known_character_names 失效。
        """
        cached = getattr(self, "_cached_character_names", None)
        if cached is not None:
            return cached
        names: list[str] = []
        try:
            for entry in _roleplay_api().list_characters():
                name = (entry.get("name") or "").strip()
                # 过滤太短（1 字，常见于普通词）与太长（>8 字，几乎不是角色名）的噪声
                if 2 <= len(name) <= 8:
                    names.append(name)
        except Exception:  # noqa: BLE001
            pass
        self._cached_character_names = names
        return names

    def _clean_assistant_text(self, text: str) -> str:
        """无角色扮演时清洗助手文本里的角色化残留，供落盘与下发前统一调用。"""
        if self._persona_text:
            return text
        return self._strip_roleplay_tone(text)

    def _build_history(self) -> str:
        """从记忆中构建对话历史文本（仅最近 10 轮，避免旧话题干扰）。"""
        ctx = self._memory.get_context()
        # 只取最后 10 轮（20 条消息），超出部分由 memory_context 承载
        recent = ctx[-20:] if len(ctx) > 20 else ctx
        lines = []
        for msg in recent:
            role = msg["role"]
            content = msg["content"][:500]  # 单条截断
            # 无角色设定时，清洗历史 assistant 消息里的角色化残留（治本：移除模型会模仿的样例）
            if role == "assistant" and not self._persona_text:
                # 先剥离装饰壳（依赖换行锚定），再做角色语气清洗（会把换行压成空格）
                content = self._strip_roleplay_tone(_sanitize_tool_text(content))
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "(空)"

    def _build_prompt(self, force_text_hint: str | None = None) -> list[dict]:
        """组装 system prompt + 语义匹配的工具推荐。

        force_text_hint 为强制收尾指令，仅本次循环注入 system prompt，不落盘记忆。
        Boss 模式：额外注入 Worker 轨迹摘要（如果存在活跃的后台任务）。
        Worker 模式：跳过角色扮演清洗，使用纯任务上下文。
        """
        is_worker = getattr(self, "_agent_role", None) == "worker"
        is_boss = getattr(self, "_agent_role", None) == "boss"
        history = self._build_history()
        memory_context = _sanitize_tool_text(self._memory.inject_system_context())
        # 无角色时连短期记忆段也清洗，避免旧角色对话经「记忆」而非「历史」回灌
        # Worker 模式跳过：buffer memory 无角色污染，清洗反而误伤任务文本
        if not self._persona_text and not is_worker:
            memory_context = self._strip_roleplay_tone(memory_context)
        professional_memory_context = getattr(self, "_professional_memory_context", "") if is_worker else ""
        if professional_memory_context:
            memory_context = (
                memory_context + "\n\n" + professional_memory_context
                if memory_context else professional_memory_context
            )
        # 预加载的 Observation（注入到 system 上下文区域，不扰乱对话历史）
        if self._preloaded_observations:
            obs_text = "\n".join(self._preloaded_observations)
            memory_context = (
                memory_context + "\n\n## 预加载信息（请以此为准）\n" + obs_text
                if memory_context else "## 预加载信息\n" + obs_text
            )
        # Boss 模式：注入 Worker 轨迹摘要（coordinator 在每轮对话前设置）
        if is_boss:
            worker_summary = getattr(self, "_worker_trace_summary", "")
            if worker_summary:
                memory_context = (
                    memory_context + "\n\n## 🔬 后台 Worker 进展\n" + worker_summary
                    if memory_context else "## 🔬 后台 Worker 进展\n" + worker_summary
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
        # 无角色时把强约束追加到 system prompt 末尾，利用 recency bias 进一步抑制角色化表达
        # Worker 模式跳过：Worker 不做角色扮演，不需要此约束
        if not self._persona_text and not is_worker:
            sys_prompt += _roleplay_api()._NO_ROLEPLAY_CONSTRAINT
        # 强制收尾指令（仅本次循环生效，不污染持久上下文）
        if force_text_hint:
            sys_prompt += "\n\n" + force_text_hint
        # 用户情绪感知提示（平静时为空串，自动跳过，避免噪声）
        # Worker 模式跳过：后台任务无需情绪感知
        if not is_worker:
            emotion_hint = getattr(self, "_emotion_hint", "") or ""
            if emotion_hint:
                sys_prompt += emotion_hint
        return [{"role": "system", "content": sys_prompt}]

    def _compile_roleplay_section(self) -> str:
        """构建角色设定段落：有 persona 时静态人设 + 每轮状态 + 动态叠加层；无则强约束标准助手语气。

        Worker 模式：返回纯任务指令，不注入任何角色设定或动态状态。
        """
        # Worker 模式：纯任务指令，不进行角色扮演
        if getattr(self, "_agent_role", None) == "worker":
            return (
                "【Worker 模式】你是后台任务执行 Agent，专注完成指定任务。"
                "不进行角色扮演，以标准技术语气回答。"
            )
        if self._persona_text:
            stance = self._memory.core.build_stance_injection(self._character_card) if self._memory else ""
            section = self._persona_text
            if stance:
                section += "\n\n## 当前状态\n" + stance
            # 动态信息机制：年龄/关系/叙事 + 记忆层幂律复苏（仅运行时叠加，绝不回写角色卡）
            user_msg = getattr(self, "_user_message", "") or ""
            dyn = self._memory.core.build_dynamic_overlay(user_msg, stage_name="") if self._memory else ""
            if dyn:
                section += "\n\n## 动态情境（仅此刻生效，不得视为角色卡固定设定）\n" + dyn
            return section
        return (
            "【系统提示】当前未启用角色扮演。"
            "你必须以标准助手语气回答，禁止出现\"喵\"、动作描写、自称等任何角色化表达。"
        )

    def _select_prompt_tools(self) -> tuple[list, int]:
        """按语义匹配筛选相关工具，并强制保留通用基础工具，返回 (工具列表, 工具总数)。"""
        all_tools = self._tools.list_tools()
        # 角色扮演场景下跳过排名（prompt 已限制工具，且 personality 不调用工具）
        if self._persona_text:
            ranked_names = {"search_tools"}
        elif self._auto_filter_tools:
            matcher = get_matcher()
            ranked = matcher.rank(self._user_message, top_k=20)
            ranked_names = {r[0] for r in ranked}
        else:
            # 用户关闭自动筛选：暴露全部工具，不做语义裁剪。
            ranked_names = {t.spec.name for t in all_tools}
        # 强制保留通用基础工具（不被匹配丢弃）
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
        """语义预加载：关键词匹配前置激活工具，结果以 Observation 注入 context。

        纯关键词匹配 + 本地计算，不调 LLM/网络。总时长保证 <350ms。
        """
        t0 = time.time()
        msg_lower = message.lower()
        preloads = self._collect_time_observations(msg_lower)
        preloads += self._collect_system_observations(msg_lower)
        # 联网类预加载已移除：天气/热榜/换算/网络IP/随机等改由 web_search 与 run_code 承担，
        # 避免指向已收敛下线的专用工具名而误导模型。
        # 存入实例变量（不写入对话历史，避免破坏 ReAct 格式）
        self._preloaded_observations = preloads if preloads else []
        elapsed = (time.time() - t0) * 1000
        if elapsed > _PRELOAD_BUDGET_MS:
            _LOGGER.warning("上下文预加载超时 %.0fms（上限 %dms）", elapsed, _PRELOAD_BUDGET_MS)

    def _collect_time_observations(self, msg_lower: str) -> list[str]:
        """命中时间/日期/时区关键词时，本地计算当前时间与时区（不调 LLM）。"""
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
        """命中系统/主机关键词时，本地取主机名、系统、架构、用户名（不调 LLM）。"""
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