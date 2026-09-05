"""AI 对话 - 终端 UI（TUI）客户端，基于 Textual。

默认由 chat.py 启动（python chat.py）。纯文本模式可用 python chat.py --plain。

布局：顶栏(提供方/模型) + 可滚动消息区 + 底部输入栏 + 状态栏。
消息以 rich.Panel 渲染：用户=青、AI=品红(Markdown)、系统=黄/红。
流式生成时逐 token 更新 AI 气泡；Ctrl+C 中断生成、Ctrl+Q 退出。
"""
from __future__ import annotations

import asyncio
import io
import sys
import time

from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown

# 终端旋转光标动画帧（braille spinner）
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Header, Footer, Input, Static, Button

# 当本文件作为脚本运行（python src/cli/chat_tui.py）时，脚本目录（src/cli）在 sys.path[0]，
# 但 backend 包位于项目根，且同目录 chat.py 为兄弟模块。这里把项目根加入 sys.path。
from pathlib import Path as _Path
_PROJ_ROOT = _Path(__file__).resolve().parent.parent.parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from backend.models import ChatRequest
from chat import (
    Session,
    handle_command,
    _run_chat,
    save,
)


class ChatTuiApp(App):
    CSS = """
    Screen { background: $surface; layout: vertical; }

    Header {
        background: $primary;
        color: $text;
    }
    Header #subtitle { color: $text-muted; }

    #conv {
        height: 1fr;
        padding: 1 2;
        background: $background;
    }
    #conv > Static {
        margin: 0 0 1 0;
        height: auto;
    }
    .metrics {
        color: $text-muted;
        margin: 0 0 1 2;
        height: auto;
    }

    #bar {
        height: auto;
        padding: 0 1 1 1;
    }
    #think_toggle {
        min-width: 16;
        margin: 0 1 0 0;
    }
    #prompt {
        margin: 0;
        padding: 1 2;
        border: round $accent;
        background: $boost;
    }
    #prompt:focus {
        border: round $secondary;
    }

    Footer { background: $primary-darken-1; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+c", "cancel", "中断生成"),
        ("t", "toggle_think", "显隐思维链"),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._active_task: asyncio.Task | None = None
        self._current: Static | None = None     # 当前正在生成的 AI 回答气泡
        self._partial: str = ""
        self._streaming: bool = False
        self._anim_timer = None                 # 统一动画/打字机计时器
        self._stream_pending: str = ""          # 已收到但尚未显示的网络文本（回答）
        self._stream_shown: str = ""            # 已显示文本（回答）
        self._stream_done: bool = False
        # —— 计时与指标 ——
        self._start_time: float = 0.0           # 请求发出时刻
        self._first_token_time: float | None = None  # 首个 token/思维链到达（首字延迟）
        self._last_usage: dict = {}             # 最近一次 done 事件返回的 usage
        self._spinner_idx: int = 0
        self._loading: bool = False             # 是否处于“等待首个 token”的加载窗口
        # —— 思维链气泡（深度思考时自动出现）——
        self._reason_current: Static | None = None
        self._reason_pending: str = ""
        self._reason_shown: str = ""
        self._reason_visible: bool = True       # 是否显示思维链（按 t 切换）
        # —— 深度思考开关：是否让模型真正思考（按钮切换；与 t 键的“显隐”是两回事）——
        _eb = self.session.config.parameters.extra_body
        self._thinking_enabled: bool = not (
            isinstance(_eb, dict) and _eb.get("thinking", {}).get("type") == "disabled"
        )

    # ---------- 布局 ----------
    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="conv")
        with Horizontal(id="bar"):
            yield Button(
                "💡 深度思考: 开",
                id="think_toggle",
                variant="success",
            )
            yield Input(id="prompt", placeholder="输入消息，Enter 发送；以 / 开头为命令")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "AI 对话"
        self.update_header()
        # 按初始状态刷新“深度思考”按钮外观
        btn = self.query_one("#think_toggle", Button)
        self._refresh_think_button(btn)
        self.query_one(Input).focus()
        lines = [
            "欢迎使用 AI 对话（终端 UI 模式）。",
            "· 直接输入文本并回车即可发送；Enter 发送，空行忽略。",
            "· 以 / 开头为命令：/help 查看全部，/config 查看配置，/exit 退出。",
            "· 快捷键：Ctrl+C 中断生成，Ctrl+Q 退出，t 显隐思维链。",
            "· 底部「💡 深度思考」按钮可开/关深度思考（关闭则模型不展示思维链）。",
        ]
        if self.session.pending_images:
            lines.append(f"· 已附带 {len(self.session.pending_images)} 张待发送图片。")
        self.add_system("\n".join(lines))

    def update_header(self) -> None:
        cfg = self.session.config
        sub = f"{cfg.active_provider or '?'} / {cfg.active_model or '?'}"
        sub += "  · 深度思考: " + ("开" if self._thinking_enabled else "关")
        if self.session.active_id:
            sub += f"  · 会话 {self.session.active_id[:8]}"
        self.sub_title = sub

    # ---------- 消息渲染 ----------
    def make_user(self, text: str) -> Panel:
        return Panel(Text(text), title="你", border_style="cyan", padding=(1, 1))

    def make_ai(self, text: str) -> Panel:
        if not text.strip():
            text = "…"
        try:
            body = Markdown(text)
        except Exception:
            body = Text(text)
        return Panel(
            body,
            title="AI",
            border_style="magenta",
            padding=(1, 1),
        )

    def make_reason(self, text: str) -> Panel:
        """思维链气泡：暗色调（蓝灰）、与正文明显区分。"""
        if not text.strip():
            text = "…"
        try:
            body = Markdown(text)
        except Exception:
            body = Text(text)
        return Panel(
            body,
            title="💭 思维链",
            border_style="blue",
            padding=(1, 1),
        )

    def make_system(self, text: str, err: bool = False) -> Panel:
        return Panel(
            Text(text),
            title="系统",
            border_style="red" if err else "yellow",
            padding=(1, 1),
        )

    def scroll_conv(self) -> None:
        self.query_one("#conv", VerticalScroll).scroll_end(animate=False)

    def add_user(self, text: str) -> None:
        self.query_one("#conv", VerticalScroll).mount(Static(self.make_user(text)))
        self.scroll_conv()

    def add_system(self, text: str, err: bool = False) -> None:
        self.query_one("#conv", VerticalScroll).mount(Static(self.make_system(text, err)))
        self.scroll_conv()

    # ---------- 发送 / 流式 ----------
    async def send(self, text: str) -> None:
        self.add_user(text)

        req = ChatRequest(
            conversation_id=self.session.active_id,
            provider=self.session.config.active_provider or None,
            model=self.session.config.active_model or None,
            system_prompt=self.session.config.system_prompt,
            parameters=self.session.config.parameters,
            content=text,
            images=self.session.pending_images or None,
        )
        self.session.pending_images = []

        # —— 计时 / 状态复位 ——
        self._start_time = time.monotonic()
        self._first_token_time = None
        self._last_usage = {}
        self._stream_pending = ""
        self._stream_shown = ""
        self._reason_pending = ""
        self._reason_shown = ""
        self._stream_done = False
        self._streaming = True
        self._loading = True

        # —— 加载占位气泡：深度思考显示“💭 思维链”占位，否则显示“AI”占位；
        #    由 _tick 旋转光标动画填充，收到首个事件后自动转为正式内容。 ——
        if self._thinking_enabled:
            self._reason_current = Static(
                Panel(Text("⠋ 连接中…"), title="💭 思维链", border_style="blue", padding=(1, 1)),
                id="ai-reason",
            )
            self._reason_current.display = self._reason_visible
            self.query_one("#conv", VerticalScroll).mount(self._reason_current)
        else:
            self._current = Static(
                Panel(Text("⠋ 连接中…"), title="AI", border_style="magenta", padding=(1, 1)),
                id="ai-stream",
            )
            self.query_one("#conv", VerticalScroll).mount(self._current)
        self.scroll_conv()

        # —— 统一动画计时器：旋转光标 + 打字机逐字 + 收尾定稿 ——
        if self._anim_timer is not None:
            self._anim_timer.stop()
        self._anim_timer = self.set_interval(1 / 30, self._tick)

        try:
            async for ev in _run_chat(req):
                t = ev.get("type")
                if t == "meta":
                    if ev.get("conversation_id"):
                        self.session.active_id = ev["conversation_id"]
                        self.update_header()
                elif t == "reasoning":
                    # 思维链增量（深度思考模型返回）
                    if self._loading:
                        self._loading = False
                        if self._first_token_time is None:
                            self._first_token_time = time.monotonic()
                    if self._reason_current is None:
                        self._reason_current = Static(
                            Panel(Text(""), title="💭 思维链", border_style="blue", padding=(1, 1)),
                            id="ai-reason",
                        )
                        self._reason_current.display = self._reason_visible
                        self.query_one("#conv", VerticalScroll).mount(self._reason_current)
                        self.scroll_conv()
                    self._reason_pending += ev["content"]
                elif t == "token":
                    if self._loading:
                        self._loading = False
                        if self._first_token_time is None:
                            self._first_token_time = time.monotonic()
                    if self._current is None:
                        self._current = Static(
                            Panel(Text(""), title="AI", border_style="magenta", padding=(1, 1)),
                            id="ai-stream",
                        )
                        self.query_one("#conv", VerticalScroll).mount(self._current)
                    self._stream_pending += ev["content"]
                elif t == "error":
                    self._loading = False
                    err_txt = f"\n\n[错误: {ev['message']}]"
                    if self._current is None and self._reason_current is None:
                        self._current = Static(
                            Panel(Text(err_txt), title="AI", border_style="magenta", padding=(1, 1)),
                            id="ai-stream",
                        )
                        self.query_one("#conv", VerticalScroll).mount(self._current)
                    elif self._current is not None:
                        self._stream_pending += err_txt
                    else:
                        self._reason_pending += err_txt
                    self._stream_done = True
                elif t == "done":
                    self._last_usage = ev.get("usage", {}) or {}
                    self._stream_done = True
        except asyncio.CancelledError:
            self._loading = False
            if self._reason_current is not None:
                self._reason_pending += "\n\n_(已中断思考)_"
            self._stream_pending += "\n\n_(已中断生成)_"
            self._stream_done = True
        except Exception as e:  # noqa: BLE001
            self._loading = False
            self._stream_pending += f"\n\n[异常: {e}]"
            self._stream_done = True
        # 注意：不在这里停表/定稿——交给 _tick 把剩余 pending 打完、显示指标后收尾。

    # ---------- 动画 / 打字机：旋转光标 + 逐字 + 收尾定稿 ----------
    def _tick(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER)
        spin = _SPINNER[self._spinner_idx]

        # 1) 加载窗口：仅有占位气泡、尚未收到任何内容 → 旋转光标“思考中”
        if self._loading:
            if self._reason_current is not None:
                msg, title, border = "模型正在深度思考", "💭 思维链", "blue"
            else:
                msg, title, border = "正在生成回答", "AI", "magenta"
            target = self._reason_current or self._current
            if target is not None:
                target.update(
                    Panel(Text(f"{spin} {msg}…"), title=title, border_style=border, padding=(1, 1))
                )
            return

        # 2) 思维链：把 pending 平滑“滴”出来
        if self._reason_current is not None and self._reason_pending:
            take = max(1, len(self._reason_pending) // 30)
            self._reason_shown += self._reason_pending[:take]
            self._reason_pending = self._reason_pending[take:]
        # 3) 正文：同上
        if self._current is not None and self._stream_pending:
            take = max(1, len(self._stream_pending) // 30)
            self._stream_shown += self._stream_pending[:take]
            self._stream_pending = self._stream_pending[take:]

        # 4) 流式进行中：末尾加旋转光标表示“仍在生成”
        streaming = not self._stream_done
        if self._reason_current is not None:
            self._update_reason(self._reason_shown + (f" {spin}" if streaming else ""))
        if self._current is not None:
            self._update_stream(self._stream_shown + (f" {spin}" if streaming else ""))

        # 5) 收尾：生成结束且 pending 清空 → 定稿 Markdown + 显示指标 + 停表
        if self._stream_done and not self._stream_pending and not self._reason_pending:
            self._finish_response()

    def _finish_response(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None
        total = time.monotonic() - self._start_time
        ttft = (self._first_token_time - self._start_time) if self._first_token_time else None

        # 定稿：把整段交给 Markdown 解析一次（思维链/正文分开）
        if self._reason_current is not None:
            if self._reason_shown.strip():
                self._reason_current.update(self.make_reason(self._reason_shown))
            else:
                self._reason_current.remove()  # 占位但无内容（极少见）→ 移除空气泡
                self._reason_current = None
        if self._current is not None:
            self._current.update(self.make_ai(self._stream_shown))

        self._append_metrics(total, ttft)

        self._current = None
        self._reason_current = None
        self._streaming = False
        self._loading = False
        self.update_header()

    def _append_metrics(self, total: float, ttft: float | None) -> None:
        """在回答下方追加一行指标：总耗时 / 首字延迟 / token 用量。"""
        u = self._last_usage or {}
        pt = int(u.get("prompt_tokens", 0) or 0)
        ct = int(u.get("completion_tokens", 0) or 0)
        det = u.get("completion_tokens_details") or {}
        rtok = int((det.get("reasoning_tokens") if isinstance(det, dict) else 0) or 0)
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "—"
        line = (f"⏱ 总耗时 {total:.2f}s  ·  首字延迟 {ttft_s}  ·  "
                f"token 共 {pt + ct}（提示 {pt} / 生成 {ct} / 思考 {rtok}）")
        self.query_one("#conv", VerticalScroll).mount(
            Static(Text(line, style="dim"), classes="metrics")
        )
        self.scroll_conv()

    def _update_stream(self, text: str) -> None:
        if self._current is None:
            return
        self._current.update(
            Panel(Text(text), title="AI", border_style="magenta", padding=(1, 1))
        )

    def _update_reason(self, text: str) -> None:
        if self._reason_current is None:
            return
        self._reason_current.update(
            Panel(Text(text), title="💭 思维链", border_style="blue", padding=(1, 1))
        )

    # ---------- 命令 ----------
    async def run_command(self, line: str) -> None:
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            quit_app = await handle_command(self.session, line)
        finally:
            sys.stdout = old
        out = buf.getvalue()
        if out.strip():
            self.add_system(out)
        self.update_header()
        if quit_app:
            self.exit()

    # ---------- 事件 ----------
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one(Input).value = ""
        if not text:
            return
        if self._streaming:
            self.notify("正在生成中，请稍候或按 Ctrl+C 中断。")
            return
        if text.startswith("/"):
            self._active_task = asyncio.create_task(self.run_command(text))
        else:
            self._active_task = asyncio.create_task(self.send(text))

    def action_cancel(self) -> None:
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()
            self._streaming = False
            self.notify("已请求中断生成")
        else:
            self.notify("当前没有正在进行的生成")

    def action_toggle_think(self) -> None:
        """切换思维链显隐（t 键）。默认显示；开启深度思考但想只看结论时可隐藏。"""
        self._reason_visible = not self._reason_visible
        if self._reason_current is not None:
            self._reason_current.display = self._reason_visible
        self.notify("思维链：" + ("显示" if self._reason_visible else "隐藏"))

    # ---------- 深度思考开关 ----------
    def _refresh_think_button(self, btn: Button) -> None:
        btn.label = "💡 深度思考: " + ("开" if self._thinking_enabled else "关")
        btn.variant = "success" if self._thinking_enabled else "error"

    def _apply_thinking(self) -> None:
        """把开关状态写入 parameters.extra_body：开=交给模型默认(思考)，
        关=显式关闭思考（thinking.type=disabled，模型不再返回思维链）。"""
        if self._thinking_enabled:
            self.session.config.parameters.extra_body = None
        else:
            self.session.config.parameters.extra_body = {"thinking": {"type": "disabled"}}

    def _toggle_thinking_mode(self) -> None:
        """深度思考开/关（按钮与 d 键共用）。"""
        self._thinking_enabled = not self._thinking_enabled
        self._apply_thinking()
        self._refresh_think_button(self.query_one("#think_toggle", Button))
        self.update_header()
        save(self.session)  # 持久化偏好，下次启动仍生效
        self.notify("深度思考：" + ("开启（模型会展示思维链）" if self._thinking_enabled
                                    else "关闭（模型不再思考）"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "think_toggle":
            self._toggle_thinking_mode()
