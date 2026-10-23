"""AI 对话 - 命令行客户端。

交互模式：     python chat.py
单次提问：     python chat.py "你的问题"
查看配置：     python chat.py --config
列出会话：     python chat.py --list

复用 backend 包（storage / config / chat / providers），
完全移除 Web 依赖（FastAPI / 前端）。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import ctypes
import json
import mimetypes
import shlex
import sys
from pathlib import Path


from ..server.config import load_config, save_config, get_provider, ensure_dirs
from ..server import storage
from ..server.models import (
    AppConfig,
    ChatRequest,
    ProviderConfig,
)

ensure_dirs()

MASK = "********"
PARAM_KEYS = ("temperature", "top_p", "max_tokens", "frequency_penalty", "presence_penalty")


# ---------- 终端颜色 ----------
def _supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            ENABLE_VT = 0x0004
            h = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            kernel32.GetConsoleMode(h, ctypes.byref(mode))
            kernel32.SetConsoleMode(h, mode.value | ENABLE_VT)
            return True
        except Exception:
            return False
    return True


USE_COLOR = _supports_color()


def c(text: str, color: str) -> str:
    # 逐次判定 tty：非终端（管道/被 TUI 捕获）时不带颜色，避免 ANSI 乱码
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}\033[0m"


C_USER = "\033[1;36m"   # 青
C_AI = "\033[1;35m"     # 品红
C_SYS = "\033[1;33m"    # 黄
C_DIM = "\033[2m"       # 暗
C_GREEN = "\033[1;32m"


class Session:
    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        self.active_id: str | None = None        # 当前会话 id
        self.pending_images: list[str] = []      # 下一条消息携带的图片 data URI


# ---------- 工具 ----------
def file_to_data_uri(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


async def do_send(session: Session, text: str, images: list[str] | None) -> None:
    req = ChatRequest(
        conversation_id=session.active_id,
        provider=session.config.active_provider or None,
        model=session.config.active_model or None,
        system_prompt=session.config.system_prompt,
        parameters=session.config.parameters,
        content=text,
        images=images or None,
    )
    sys.stdout.write(c("AI: ", C_AI))
    sys.stdout.flush()
    _in_reason = False
    try:
        async for ev in storage_run(req, session):
            t = ev.get("type")
            if t == "meta":
                if ev.get("conversation_id"):
                    session.active_id = ev["conversation_id"]
                if ev.get("title") and session.active_id:
                    pass  # 标题由 storage 维护
            elif t == "reasoning":
                # 深度思考模式：自动显示思维链（暗色），结束后切回正文
                if not _in_reason:
                    sys.stdout.write("\n")
                    sys.stdout.write(c("\n💭 思维链：", C_DIM))
                    _in_reason = True
                sys.stdout.write(c(ev["content"], C_DIM))
                sys.stdout.flush()
            elif t == "token":
                if _in_reason:
                    sys.stdout.write("\n")
                    sys.stdout.write(c("\n💡 回答：", C_AI))
                    _in_reason = False
                sys.stdout.write(ev["content"])
                sys.stdout.flush()
            elif t == "error":
                sys.stdout.write("\n")
                print(c("错误: " + ev["message"], C_SYS))
            elif t == "done":
                pass
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        print(c("(已中断生成)", C_SYS))
        return
    sys.stdout.write("\n")


# run_chat 位于 backend.chat，此处延迟导入以避免任何循环
from ..server.chat import run_chat as _run_chat
from ..server.discovery import discover_models


async def storage_run(req: ChatRequest, session: Session):
    async for ev in _run_chat(req):
        yield ev


# ---------- 命令 ----------
def help_text() -> str:
    return f"""\
{c("命令列表", C_SYS)}
  /help              显示本帮助
  /new               新建会话
  /list              列出所有会话
  /switch <id>       切换到指定会话
  /delete <id>       删除会话
  /config            显示当前配置
  /provider <id>     切换当前提供方
  /model <model>     切换当前模型
  /system <prompt>   设置系统提示词（省略参数可查看）
  /param <k> <v>     设置参数（{', '.join(PARAM_KEYS)}）
  /addprovider       添加提供方（引导式：输 key+地址→自动检测连通性→拉取模型列表→选择保存）
  /connect           同 /addprovider（引导式配置并保存）
  /setkey <id> <key> 设置某提供方的 API Key
  /export [id] [fmt] 导出会话到 <id>.<fmt>（fmt=json|md，默认 json）
  /import <file>     从文件导入会话
  /image <path...>   为下一条消息附加图片（可多个）
  /clearimg          清除待发送的图片
  /exit, /quit       退出

{c("说明", C_SYS)}：直接输入文本即可发送；Enter 发送，空行忽略。
  一次提问：python chat.py "你的问题"
  纯命令行（无 TUI）：python chat.py --plain
"""


def _cast_param(key: str, value: str):
    if key in ("max_tokens",):
        return int(float(value))
    return float(value)


def save(session: Session) -> None:
    save_config(session.config)


def cmd_config(session: Session) -> None:
    cfg = session.config
    print(c("=== 当前配置 ===", C_SYS))
    print(f"  提供方数：{len(cfg.providers)}")
    for p in cfg.providers:
        mark = "*" if p.id == cfg.active_provider else " "
        key_hint = MASK if p.api_key else "(未设置)"
        print(f"  {mark} {p.id}  [{p.name}] type={p.type} base={p.base_url or '(默认)'}")
        print(f"      模型: {', '.join(p.models) or '(无)'}  key: {key_hint}")
    print(f"  当前模型：{cfg.active_model or '(未选择)'}")
    print(f"  系统提示：{cfg.system_prompt}")
    pr = cfg.parameters
    print(f"  参数：temp={pr.temperature} top_p={pr.top_p} max_tokens={pr.max_tokens} "
          f"freq={pr.frequency_penalty} pres={pr.presence_penalty}")
    if session.active_id:
        print(f"  当前会话：{session.active_id}")


def cmd_list(session: Session) -> None:
    convs = storage.list_conversations()
    if not convs:
        print(c("（暂无会话）", C_DIM))
        return
    print(c("=== 会话列表 ===", C_SYS))
    for cv in convs:
        mark = "*" if cv["id"] == session.active_id else " "
        print(f"  {mark} {cv['id']}  {cv['title']}  "
              f"(消息 {cv['message_count']}, 更新 {_fmt_time(cv['updated_at'])})")


def _fmt_time(ts: float) -> str:
    if not ts:
        return "-"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def parse_model_selection(raw: str, models: list[str]) -> list[str]:
    """解析用户对模型列表的选择：序号 / 逗号分隔 / 区间 / all。"""
    raw = (raw or "").strip()
    if not raw or raw.lower() == "all":
        return list(models)
    chosen: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            for n in range(lo, hi + 1):
                if 1 <= n <= len(models):
                    chosen.append(models[n - 1])
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= len(models):
                chosen.append(models[n - 1])
    return chosen


async def fetch_and_select_models(ptype: str, base: str, key: str) -> list[str] | None:
    """自动检测连通性并拉取模型列表，让用户挑选；取消返回 None。"""
    print(c("正在检测连通性并获取模型列表…", C_SYS))
    try:
        models = await discover_models(ptype, base, key)
    except Exception as e:  # noqa: BLE001
        print(c(f"检测失败：{e}", C_SYS))
        if sys.stdin.isatty() and input("  改为手动输入模型列表？(y/N): ").strip().lower() == "y":
            ms = input("  模型（逗号分隔）: ").strip()
            return [m.strip() for m in ms.split(",") if m.strip()]
        return None

    if not models:
        print(c("连通正常，但未返回任何模型。", C_SYS))
        if sys.stdin.isatty() and input("  手动输入模型列表？(y/N): ").strip().lower() == "y":
            ms = input("  模型（逗号分隔）: ").strip()
            return [m.strip() for m in ms.split(",") if m.strip()]
        return []

    print(c(f"检测到 {len(models)} 个模型：", C_GREEN))
    for i, m in enumerate(models, 1):
        print(f"  [{i}] {m}")
    sel = input("  选择模型（序号/逗号分隔/区间 如 1,3-5，或 all，可空=全部）: ").strip()
    chosen = parse_model_selection(sel, models) or models
    return chosen


async def cmd_addprovider(session: Session, args: list[str] | None = None) -> None:
    # 非交互（TUI / 管道传参）：直接按参数构建，不自动探测
    if args:
        pid = args[0]
        ptype = args[1] if len(args) > 1 else "openai_compat"
        key = args[2] if len(args) > 2 else ""
        models = [m.strip() for m in (args[3].split(",") if len(args) > 3 else []) if m.strip()]
        name = pid
        base = None
        prov = ProviderConfig(id=pid, name=name, type=ptype, base_url=base, api_key=key, models=models)
        session.config.providers.append(prov)
        if not session.config.active_provider:
            session.config.active_provider = pid
            if models:
                session.config.active_model = models[0]
        save(session)
        print(c(f"已添加提供方 {pid}，模型数 {len(models)}。", C_GREEN))
        return

    if not sys.stdin.isatty():
        print(c("用法：/addprovider <id> <type> <key> [models_csv]", C_SYS))
        return

    # 交互引导式：输入 key + 地址 → 自动检测 → 拉取模型 → 选择 → 保存
    print(c("添加提供方（引导式）：输入 API Key 与请求地址后，将自动检测连通性并获取模型列表。", C_SYS))
    pid = input("  id（如 openai / deepseek）: ").strip()
    if not pid:
        print(c("已取消。", C_DIM))
        return
    name = input("  显示名（可空，默认与 id 相同）: ").strip() or pid
    ptype = input("  type（openai_compat | anthropic | ollama，默认 openai_compat）: ").strip() or "openai_compat"
    base_hint = ("  Ollama 原生根地址（如 http://127.0.0.1:11434，不要带 /v1）: "
                 if ptype == "ollama" else
                 "  请求地址 base_url（如 https://api.openai.com/v1）: ")
    base = input(base_hint).strip()
    key = input("  api_key: ").strip()

    if base or key:
        models = await fetch_and_select_models(ptype, base, key)
        if models is None:  # 用户取消
            print(c("已取消。", C_DIM))
            return
    else:
        ms = input("  模型（逗号分隔）: ").strip()
        models = [m.strip() for m in ms.split(",") if m.strip()]

    prov = ProviderConfig(id=pid, name=name, type=ptype, base_url=base or None, api_key=key, models=models)
    session.config.providers.append(prov)
    if not session.config.active_provider:
        session.config.active_provider = pid
        if models:
            session.config.active_model = models[0]
    save(session)
    print(c(f"已添加提供方 {pid}，已保存 {len(models)} 个模型。", C_GREEN))


def cmd_setkey(session: Session, pid: str, key: str) -> None:
    for p in session.config.providers:
        if p.id == pid:
            p.api_key = key
            save(session)
            print(c(f"已更新 {pid} 的 API Key。", C_GREEN))
            return
    print(c(f"未找到提供方：{pid}", C_SYS))


async def handle_command(session: Session, line: str) -> bool:
    """返回 True 表示退出。"""
    try:
        parts = shlex.split(line)
    except ValueError as e:
        print(c(f"参数解析错误：{e}", C_SYS))
        return False
    if not parts:
        return False
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/help":
        print(help_text())
    elif cmd == "/new":
        session.active_id = None
        print(c("已新建会话（发送消息后生成）。", C_GREEN))
    elif cmd == "/list":
        cmd_list(session)
    elif cmd == "/switch":
        if not args:
            print(c("用法：/switch <id>", C_SYS))
        elif storage.get_conversation(args[0]):
            session.active_id = args[0]
            print(c(f"已切换到会话 {args[0]}。", C_GREEN))
        else:
            print(c(f"会话不存在：{args[0]}", C_SYS))
    elif cmd == "/delete":
        if not args:
            print(c("用法：/delete <id>", C_SYS))
        elif storage.delete_conversation(args[0]):
            if session.active_id == args[0]:
                session.active_id = None
            print(c(f"已删除会话 {args[0]}。", C_GREEN))
        else:
            print(c(f"会话不存在：{args[0]}", C_SYS))
    elif cmd == "/config":
        cmd_config(session)
    elif cmd == "/provider":
        if not args:
            print(c("用法：/provider <id>", C_SYS))
        elif get_provider(args[0]):
            session.config.active_provider = args[0]
            models = get_provider(args[0]).models
            if models and session.config.active_model not in models:
                session.config.active_model = models[0]
            save(session)
            print(c(f"已切换提供方 {args[0]}。", C_GREEN))
        else:
            print(c(f"未找到提供方：{args[0]}", C_SYS))
    elif cmd == "/model":
        if not args:
            print(c("用法：/model <model>", C_SYS))
        else:
            session.config.active_model = args[0]
            save(session)
            print(c(f"已设置模型 {args[0]}。", C_GREEN))
    elif cmd == "/system":
        if not args:
            print(c(f"当前系统提示：{session.config.system_prompt}", C_DIM))
        else:
            session.config.system_prompt = " ".join(args)
            save(session)
            print(c("已更新系统提示。", C_GREEN))
    elif cmd == "/param":
        if len(args) < 2 or args[0] not in PARAM_KEYS:
            print(c(f"用法：/param <{'|'.join(PARAM_KEYS)}> <值>", C_SYS))
        else:
            try:
                val = _cast_param(args[0], args[1])
            except ValueError:
                print(c("参数值无效（应为数字）。", C_SYS))
                return False
            setattr(session.config.parameters, args[0], val)
            save(session)
            print(c(f"已设置 {args[0]} = {val}。", C_GREEN))
    elif cmd in ("/addprovider", "/connect"):
        await cmd_addprovider(session, args)
    elif cmd == "/setkey":
        if len(args) < 2:
            print(c("用法：/setkey <id> <key>", C_SYS))
        else:
            cmd_setkey(session, args[0], " ".join(args[1:]))
    elif cmd == "/export":
        cid = args[0] if args else session.active_id
        fmt = args[1] if len(args) > 1 else "json"
        if not cid:
            print(c("没有可导出的会话（先 /new 或 /switch）。", C_SYS))
            return False
        content = storage.export_conversation(cid, fmt)
        if content is None:
            print(c(f"会话不存在：{cid}", C_SYS))
            return False
        out = Path(f"{cid}.{fmt}")
        out.write_text(content, encoding="utf-8")
        print(c(f"已导出到 {out.resolve()}", C_GREEN))
    elif cmd == "/import":
        if not args:
            print(c("用法：/import <file>", C_SYS))
        else:
            text = Path(args[0]).read_text(encoding="utf-8", errors="ignore")
            conv = storage.import_conversation(text)
            if conv is None:
                print(c("导入失败：无效的对话文件。", C_SYS))
            else:
                session.active_id = conv.id
                save(session)
                print(c(f"已导入会话 {conv.id}（{conv.title}）。", C_GREEN))
    elif cmd == "/image":
        if not args:
            print(c("用法：/image <path...>", C_SYS))
        else:
            for p in args:
                try:
                    uri = file_to_data_uri(p)
                    session.pending_images.append(uri)
                    print(c(f"已添加图片：{p}", C_GREEN))
                except Exception as e:
                    print(c(str(e), C_SYS))
    elif cmd == "/clearimg":
        session.pending_images.clear()
        print(c("已清除待发送图片。", C_DIM))
    else:
        print(c(f"未知命令：{cmd}（输入 /help 查看帮助）", C_SYS))
    return False


# ---------- 交互循环 ----------
async def repl(session: Session) -> None:
    print(c("AI 对话 CLI 已启动。输入 /help 查看命令，/exit 退出。", C_DIM))
    if not session.config.providers:
        print(c("提示：尚未配置任何提供方，先用 /addprovider 添加，或编辑 config.json。", C_SYS))
    while True:
        try:
            line = input(c("你> ", C_USER))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            continue
        if line.startswith("/"):
            try:
                if await handle_command(session, line):
                    break
            except (EOFError, KeyboardInterrupt):
                print()
                break
            continue
        images = session.pending_images or None
        session.pending_images = []
        await do_send(session, line, images)


# ---------- 单次提问 ----------
async def oneshot(session: Session, message: str, images: list[str] | None) -> None:
    await do_send(session, message, images)


# ---------- 入口 ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI 对话命令行客户端")
    p.add_argument("message", nargs="?", help="单次提问内容（省略则进入交互模式）")
    p.add_argument("--provider", help="指定提供方 id（仅本次）")
    p.add_argument("--model", help="指定模型（仅本次）")
    p.add_argument("--system", help="指定系统提示词（仅本次）")
    p.add_argument("--image", action="append", default=[], help="附加图片路径（可多次）")
    p.add_argument("--param", action="append", default=[], help="覆盖参数 key=value（可多次）")
    p.add_argument("--no-think", action="store_true",
                   help="关闭 GLM 思考链(thinking.type=disabled)，把内容首字延迟压到 <1s（GLM-4.6/4.5/4.6V 支持）")
    p.add_argument("--config", action="store_true", help="打印配置后退出")
    p.add_argument("--list", action="store_true", help="列出会话后退出")
    p.add_argument("--tui", action="store_true", help="使用终端 UI 模式（默认仍为纯命令行）")
    return p


def apply_overrides(session: Session, args: argparse.Namespace) -> None:
    if args.provider:
        session.config.active_provider = args.provider
    if args.model:
        session.config.active_model = args.model
    if args.system:
        session.config.system_prompt = args.system
    for kv in args.param:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k in PARAM_KEYS:
            try:
                setattr(session.config.parameters, k, _cast_param(k, v))
            except ValueError:
                print(c(f"忽略无效参数 {kv}", C_SYS))
    # 关闭思考链：把 thinking.type=disabled 透传给 API（GLM 系列推理模型压低首字延迟的关键）
    # 注意：智谱原生字段是顶层 "thinking":{"type":"disabled"}，而非 enable_thinking。
    if getattr(args, "no_think", False):
        session.config.parameters.extra_body = {"thinking": {"type": "disabled"}}


def main() -> None:
    args = build_parser().parse_args()
    session = Session()
    apply_overrides(session, args)

    if args.config:
        cmd_config(session)
        return
    if args.list:
        cmd_list(session)
        return

    # ★ 启动预热：把 TCP+TLS 握手移出首次提问的关键路径（尽力而为）
    try:
        from ..server.chat import prewarm_active_provider
        _ms = asyncio.run(prewarm_active_provider())
        if _ms:
            print(c(f"连接预热完成（{_ms:.0f}ms）", C_DIM))
    except Exception:
        pass  # 预热失败不影响进入对话

    # --image 统一转为待发送图片（TUI 与一次性模式均复用 pending_images）
    if args.image:
        for p in args.image:
            try:
                session.pending_images.append(file_to_data_uri(p))
            except Exception as e:
                print(c(str(e), C_SYS))

    if args.message:
        asyncio.run(oneshot(session, args.message, session.pending_images or None))
    elif args.tui:
        run_tui(session)
    else:
        # 默认：纯命令行交互模式
        try:
            asyncio.run(repl(session))
        except KeyboardInterrupt:
            print()


def run_tui(session: Session) -> None:
    try:
        from .chat_tui import ChatTuiApp
    except ImportError as e:
        print(c("未能加载终端 UI（Textual 未安装）。", C_SYS))
        print(c("请先安装依赖：pip install textual", C_SYS))
        print(c("或改用纯命令行模式：python chat.py --plain", C_DIM))
        print(c(f"(导入错误：{e})", C_DIM))
        return
    ChatTuiApp(session).run()


if __name__ == "__main__":
    main()
