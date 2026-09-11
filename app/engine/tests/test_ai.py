"""AI 对话后端 —— 集成测试 + 交互式聊天（测试结束后不退出）。

本脚本直接驱动 backend 包（config / storage / chat / providers），
对 AI 对话链路做端到端集成测试，跑完测试后**默认进入交互式对话**，
直接与后端真实 AI（默认 zhipu / glm-4.6v）聊天，证明整合成功。

【默认即真实 API】脚本默认使用 config.json 中已配置好的真实提供方
（zhipu + glm-4.6v，已写入 API Key），不再使用任何模拟回复。
如需离线调试，可显式加 --mock 切到本地 Mock 提供方。

用法：
    python test_ai.py                      # 跑测试 -> 进入真实 AI 交互聊天
    python test_ai.py --no-chat            # 只跑测试，跑完退出（CI 用）
    python test_ai.py --provider openai --model gpt-4o   # 指定其它真实提供方
    python test_ai.py --mock               # 离线调试：用 Mock 提供方（非真实 API）

测试覆盖：
    - Provider 注册、配置读写/持久化、会话 CRUD、图片解析（无需网络）
    - 真实流式生成（逐字 token + usage + 落盘）
    - 真实多模态（带图片请求，验证 vision 链路）
    - 真实上下文（用户消息确实进入模型上下文）
    - 错误路径（未知提供方 / 未指定模型）

交互模式命令：/exit /quit 退出，/new 新会话，/provider /model /system
切换，/config 查看，/list 列出会话，/help 帮助。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # 项目根（tests/ 的上一级）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import load_config, save_config, get_provider, UPLOAD_DIR
from backend import storage
from backend.models import ChatRequest, Message, ModelParameters, ProviderConfig
from backend.chat import run_chat, resolve_image
from backend.providers import get_provider_instance


# 一张纯红色图（48x48 PNG，base64），供多模态测试使用
_RED_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAAOklEQVR42u3OMQ0AAAgDsMmZfz2I"
    "wQXhaFIBzbSvREhISEhISEhISEhISEhISEhISEhISEhISEjozgL2k4yXnNnWoAAAAABJRU5ErkJggg=="
)

# ---------- 终端颜色 ----------
_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"{code}{text}\033[0m" if _USE_COLOR else text


C_GREEN = "\033[1;32m"
C_RED = "\033[1;31m"
C_YEL = "\033[1;33m"
C_CYA = "\033[1;36m"
C_DIM = "\033[2m"


def ok(s: str) -> str:
    return _c(s, C_GREEN)


def bad(s: str) -> str:
    return _c(s, C_RED)


def dim(s: str) -> str:
    return _c(s, C_DIM)


# ---------- 测试结果收集 ----------
_RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, passed, detail))
    mark = ok("PASS") if passed else bad("FAIL")
    extra = f"  {dim(detail)}" if detail else ""
    print(f"  [{mark}] {name}{extra}")


# ============================ 准备：Mock 提供方（仅 --mock 离线调试用） ============================
def ensure_mock_provider() -> None:
    cfg = load_config()
    if any(p.id == "mock" for p in cfg.providers):
        return
    cfg.providers.append(
        ProviderConfig(
            id="mock", name="Mock 模拟 (本地调试)",
            type="mock", api_key="", models=["mock-model"],
        )
    )
    save_config(cfg)


# ============================ 同步测试（无需网络） ============================
def test_provider_registry() -> None:
    try:
        from backend.providers.mock import MockProvider
        inst = get_provider_instance(ProviderConfig(id="mock", name="m", type="mock"))
        record("Provider 注册: mock 可实例化（离线类型校验）",
               isinstance(inst, MockProvider),
               f"type={type(inst).__name__}")
    except Exception as e:  # noqa: BLE001
        record("Provider 注册: mock 可实例化（离线类型校验）", False, repr(e))

    for t in ("openai_compat", "anthropic", "gemini", "mock"):
        try:
            inst = get_provider_instance(ProviderConfig(id=t, name=t, type=t))
            assert inst is not None
        except Exception as e:  # noqa: BLE001
            record(f"Provider 注册: {t}", False, repr(e))
            return
    record("Provider 注册: 全部类型可解析", True)


def test_config_roundtrip() -> None:
    cfg = load_config()
    record("配置加载: 返回 AppConfig", hasattr(cfg, "providers"), f"提供方数={len(cfg.providers)}")

    # 持久化 & 真实值保留（不遮罩）。用 mock 当安全草稿，避免覆盖真实 key。
    ensure_mock_provider()
    cfg = load_config()
    mock = next((p for p in cfg.providers if p.id == "mock"), None)
    assert mock is not None
    old = mock.api_key
    try:
        mock.api_key = "test-secret-123"
        save_config(cfg)  # 保存被修改的同一对象（不要重新 load，否则改动丢失）
        reloaded = get_provider("mock")
        record("配置持久化: API Key 真实落盘（非遮罩）",
               reloaded is not None and reloaded.api_key == "test-secret-123",
               repr(reloaded.api_key if reloaded else None))
    finally:
        mock.api_key = old
        save_config(load_config())


def test_conversation_crud() -> None:
    conv = storage.create_conversation()
    cid = conv.id
    record("会话 CRUD: 创建", bool(cid))

    storage.append_message(cid, Message(role="user", content="你好"))
    got = storage.get_conversation(cid)
    record("会话 CRUD: 追加并读取消息", got is not None and len(got.messages) == 1,
           f"消息数={len(got.messages) if got else 0}")

    lst = storage.list_conversations()
    record("会话 CRUD: 出现在列表中", any(c["id"] == cid for c in lst))

    exported = storage.export_conversation(cid, "json")
    record("会话 CRUD: 导出 JSON", exported is not None and "你好" in exported)

    imported = storage.import_conversation(exported) if exported else None
    record("会话 CRUD: 导入还原", imported is not None and len(imported.messages) == 1)

    deleted = storage.delete_conversation(cid)
    record("会话 CRUD: 删除", deleted and storage.get_conversation(cid) is None)


def test_image_resolve() -> None:
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9Q"
               "DwADhgGAWjR9awAAAABJRU5ErkJggg==")
    fname = "_test_img.png"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(base64.b64decode(png_b64))
    try:
        uri = resolve_image(f"/uploads/{fname}")
        record("图片解析: /uploads 路径转 data URI",
               uri.startswith("data:image/png;base64,"),
               f"前缀={uri[:22]}…")
    finally:
        fpath.unlink(missing_ok=True)


# ============================ 异步测试 ============================
async def _collect(req: ChatRequest) -> tuple[list[dict], str]:
    events: list[dict] = []
    conv_id = ""
    async for ev in run_chat(req):
        events.append(ev)
        if ev.get("type") == "meta" and ev.get("conversation_id"):
            conv_id = ev["conversation_id"]
    return events, conv_id


async def test_stream_real(provider: str, model: str) -> None:
    name = f"[{provider}/{model}]"
    req = ChatRequest(provider=provider, model=model,
                      content="用一句话介绍你自己。")
    try:
        events, cid = await _collect(req)
        types = [e.get("type") for e in events]
        tokens = [e for e in events if e.get("type") == "token"]
        done = [e for e in events if e.get("type") == "done"]
        errs = [e for e in events if e.get("type") == "error"]
        joined = "".join(e["content"] for e in tokens)

        if errs:
            record(f"真实流式 {name}: 服务端报错", False, errs[0].get("message", ""))
        else:
            record(f"真实流式 {name}: 产出 meta(会话id)", "meta" in types and bool(cid))
            record(f"真实流式 {name}: 产出 token 增量", len(tokens) > 0, f"片段数={len(tokens)}")
            record(f"真实流式 {name}: 产出 done(usage)",
                   len(done) > 0,
                   f"usage={done[0].get('usage') if done else None}")
            conv = storage.get_conversation(cid) if cid else None
            persisted = conv is not None and len(conv.messages) == 2
            content_ok = (conv is not None and conv.messages[-1].role == "assistant"
                          and joined in conv.messages[-1].content)
            record(f"真实流式 {name}: 落盘 user+assistant", persisted and content_ok,
                   f"消息数={len(conv.messages) if conv else 0} 回复长度={len(joined)}")
        if cid:
            storage.delete_conversation(cid)
    except Exception as e:  # noqa: BLE001
        record(f"真实流式 {name}: 异常", False, repr(e))


async def test_stream_context(provider: str, model: str) -> None:
    name = f"[{provider}/{model}]"
    secret = "青鸟-柒月-测试符"
    req = ChatRequest(provider=provider, model=model,
                      content=f"请原样复述下面这个专属代号（不要解释，只输出代号本身）：『{secret}』")
    try:
        events, cid = await _collect(req)
        tokens = [e for e in events if e.get("type") == "token"]
        errs = [e for e in events if e.get("type") == "error"]
        joined = "".join(e["content"] for e in tokens)
        if errs:
            record(f"真实上下文 {name}: 服务端报错", False, errs[0].get("message", ""))
        else:
            # 关键：用户消息必须真正进入模型上下文（验证首条消息上下文丢失 bug 未复发）
            record(f"真实上下文 {name}: 用户消息进入模型上下文",
                   secret in joined, f"命中={secret in joined}")
        if cid:
            storage.delete_conversation(cid)
    except Exception as e:  # noqa: BLE001
        record(f"真实上下文 {name}: 异常", False, repr(e))


async def test_multimodal_real(provider: str, model: str) -> None:
    name = f"[{provider}/{model}]"
    data_uri = f"data:image/png;base64,{_RED_PNG_B64}"
    req = ChatRequest(provider=provider, model=model,
                      content="这张图片的主色调是什么颜色？只回答颜色名。",
                      images=[data_uri])
    try:
        events, cid = await _collect(req)
        tokens = [e for e in events if e.get("type") == "token"]
        errs = [e for e in events if e.get("type") == "error"]
        joined = "".join(e["content"] for e in tokens)
        if errs:
            record(f"真实多模态 {name}: 服务端报错（模型可能不支持视觉）",
                   False, errs[0].get("message", ""))
        else:
            record(f"真实多模态 {name}: 带图片请求流式成功",
                   len(tokens) > 0 and len(joined) > 0,
                   f"回复前20字={joined[:20]!r}")
        if cid:
            storage.delete_conversation(cid)
    except Exception as e:  # noqa: BLE001
        record(f"真实多模态 {name}: 异常", False, repr(e))


async def test_error_paths() -> None:
    # 提供方不存在
    ev_no_provider, _ = await _collect(ChatRequest(provider="__nope__", model="x", content="hi"))
    err1 = any(e.get("type") == "error" for e in ev_no_provider)
    record("错误处理: 未知提供方返回 error 事件", err1)

    # 未指定模型（置空 active_model 触发，恢复前不动网络）
    cfg = load_config()
    snap_provider, snap_model = cfg.active_provider, cfg.active_model
    try:
        cfg.active_provider = snap_provider
        cfg.active_model = ""
        save_config(cfg)
        ev_no_model, _ = await _collect(ChatRequest(provider=snap_provider, model="", content="hi"))
        err2 = any(e.get("type") == "error" for e in ev_no_model)
        record("错误处理: 未指定模型返回 error 事件", err2)
    finally:
        cfg2 = load_config()
        cfg2.active_provider, cfg2.active_model = snap_provider, snap_model
        save_config(cfg2)


async def run_async_tests(provider: str, model: str, use_mock: bool) -> None:
    if use_mock:
        await test_stream_real("mock", "mock-model")
        await test_stream_context("mock", "mock-model")
        await test_multimodal_real("mock", "mock-model")
    else:
        await test_stream_real(provider, model)
        await test_stream_context(provider, model)
        await test_multimodal_real(provider, model)
    await test_error_paths()


# ============================ 同步入口 ============================
def run_sync_tests() -> None:
    test_provider_registry()
    test_config_roundtrip()
    test_conversation_crud()
    test_image_resolve()


# ============================ 交互式聊天（整合真实 AI，不退出） ============================
async def _send(text: str, provider: str, model: str, system: str,
                params: ModelParameters, conv_id: str | None) -> str:
    req = ChatRequest(
        conversation_id=conv_id, provider=provider, model=model,
        system_prompt=system, parameters=params, content=text,
    )
    print(_c("AI: ", C_CYA), end="", flush=True)
    new_id = conv_id
    try:
        async for ev in run_chat(req):
            t = ev.get("type")
            if t == "meta":
                if ev.get("conversation_id"):
                    new_id = ev["conversation_id"]
            elif t == "token":
                print(ev["content"], end="", flush=True)
            elif t == "error":
                print("\n" + bad("错误: " + ev["message"]))
            elif t == "done":
                pass
    except KeyboardInterrupt:
        print("\n" + dim("(已中断生成)"))
    print()
    return new_id


async def interactive(provider: str, model: str, system: str, use_mock: bool) -> None:
    mode = "Mock 离线模拟" if use_mock else "真实 API"
    print()
    print(ok("✅ 全部测试完成。") + dim(f" 以下进入交互式对话（{mode}），输入 /exit 退出。"))
    print(dim("   默认提供方: ") + provider + dim("  模型: ") + model)
    print(dim("   命令: /exit /quit 退出 · /new 新会话 · /provider <id> · /model <m> · /system <p> · /config · /list · /help"))
    cfg = load_config()
    params = cfg.parameters
    conv_id: str | None = None

    while True:
        try:
            line = input(_c("你> ", C_CYA))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            continue
        if line.startswith("/"):
            parts = line[1:].split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd in ("exit", "quit"):
                print(dim("再见。"))
                return
            elif cmd == "help":
                print(dim("命令: /exit /quit /new /provider <id> /model <m> /system <p> /config /list"))
            elif cmd == "new":
                conv_id = None
                print(ok("已新建会话（发送后生成）。"))
            elif cmd == "provider":
                if get_provider(arg):
                    provider = arg
                    m = get_provider(arg).models
                    if m:
                        model = m[0]
                    print(ok(f"已切换提供方 {arg}（模型 {model}）。"))
                else:
                    print(bad(f"未找到提供方：{arg}"))
            elif cmd == "model":
                model = arg
                print(ok(f"已设置模型 {arg}。"))
            elif cmd == "system":
                system = arg
                print(ok("已更新系统提示。"))
            elif cmd == "config":
                print(f"  提供方={provider} 模型={model}\n  系统提示={system}\n"
                      f"  参数 temp={params.temperature} top_p={params.top_p} max_tokens={params.max_tokens}")
            elif cmd == "list":
                for c in storage.list_conversations():
                    mark = "*" if c["id"] == conv_id else " "
                    print(f"  {mark} {c['id']}  {c['title']} ({c['message_count']} 条)")
            else:
                print(bad(f"未知命令：/{cmd}（/help 查看）"))
            continue
        conv_id = await _send(line, provider, model, system, params, conv_id)


# ============================ 主流程 ============================
def main() -> None:
    ap = argparse.ArgumentParser(description="AI 对话后端集成测试 + 交互式聊天（默认真实 API）")
    ap.add_argument("--no-chat", action="store_true", help="只跑测试，跑完退出")
    ap.add_argument("--mock", action="store_true", help="离线调试：用 Mock 提供方（非真实 API）")
    ap.add_argument("--provider", default="zhipu", help="交互/测试默认提供方 (默认 zhipu，真实 API)")
    ap.add_argument("--model", default="glm-4.6v", help="交互/测试默认模型 (默认 glm-4.6v)")
    ap.add_argument("--system", default=None, help="交互模式系统提示词")
    args = ap.parse_args()

    if args.mock:
        ensure_mock_provider()
        args.provider, args.model = "mock", "mock-model"

    print(_c("=== AI 对话后端 集成测试（默认真实 API） ===", C_YEL))
    print(dim(f"  目标提供方: {args.provider} / {args.model}"
               + ("  [MOCK 离线]" if args.mock else "  [真实 API]")))
    run_sync_tests()
    asyncio.run(run_async_tests(args.provider, args.model, args.mock))

    passed = sum(1 for _, p, _ in _RESULTS if p)
    total = len(_RESULTS)
    print()
    print(f"测试结果：{ok(f'{passed}/{total} 通过') if passed == total else bad(f'{passed}/{total} 通过')}"
          + ("" if passed == total else dim("  （存在失败项，请检查上方细节）")))

    if args.no_chat:
        print(dim("（--no-chat：测试结束，已退出。）"))
        return

    # ★ 关键：测试结束后不退出，进入交互式聊天（整合真实 AI）
    system = args.system or load_config().system_prompt
    asyncio.run(interactive(args.provider, args.model, system, args.mock))


if __name__ == "__main__":
    main()
