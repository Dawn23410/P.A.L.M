"""Agent 砖块：砖块注册 + SSE 流式 API。

与其他砖块的集成：
- models 砖 → capabilities["create_stream"] 做 LLM 调用
- 统一护栏（palm_sdk.guardrail）→ get_guardrail_capability() 做工具安全预检（裁决引擎砖已拆）
- conversations 砖 → 持久化对话（复用已有逻辑）
- 各砖的 agent_tools → 自动注册外部工具
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from palm_sdk.core.config import settings
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks.housekeeping import emit_entity_deleted, ENTITY_CONVERSATION, ENTITY_CHARACTER
from palm_sdk.permission import PermissionSpec, RiskLevel
from palm_sdk.guardrail.engine import get_guardrail_capability
from .core import Agent
from .schemas import AgentEvent, AgentRunRequest
from .tool_base import register_builtin_tools, get_registry
from .llm_bridge import stream_llm as _stream_llm
from .question_hub import get_question_hub
from palm_sdk.bricks._shared.interop import (
    get_roleplay_api,
    get_memory_api,
    get_evolution_api,
    get_affinity_api,
)
from palm_sdk.bricks._shared.watchdog import register_heartbeat, touch as _wd_touch


def _roleplay():
    """取角色扮演砖门面；缺失即报错（agent 依赖 roleplay，应在注册顺序中先于 agent）。"""
    api = get_roleplay_api()
    if api is None:
        raise RuntimeError("角色扮演砖未注册")
    return api


def _is_mock_run(req) -> bool:
    """mock 模式 = 请求未携带真实 LLM 供应商；此时禁用 Agent 编排执行，仅对话可用。"""
    p = getattr(req, "provider", None)
    if not p:
        return True
    if isinstance(p, dict):
        return not bool(p.get("base_url") or p.get("api_key"))
    return not bool(getattr(p, "base_url", None) or getattr(p, "api_key", None))


def _affinity():
    """取好感度砖门面；缺失即报错（好感度域 2026-08-06 拆出独立砖）。"""
    api = get_affinity_api()
    if api is None:
        raise RuntimeError("好感度砖未注册")
    return api


def _memory():
    """取记忆砖门面；缺失即报错（agent 依赖 memory）。"""
    api = get_memory_api()
    if api is None:
        raise RuntimeError("记忆砖未注册")
    return api


def _bg_scheduler():
    # 后台任务调度单例现由 evolution 砖持有；agent 经 capability 取用（注册顺序保证就绪）。
    api = get_evolution_api()
    if api is None:
        raise RuntimeError("自主进化砖未注册")
    sched = getattr(api, "scheduler", None)
    if sched is None:
        raise RuntimeError("evolution 砖未暴露 scheduler")
    return sched

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ── 工具注册 ────────────────────────────────────────────────────

def _ensure_tools() -> None:
    """注册内置工具 + 收集各砖块的外部工具。"""
    register_builtin_tools()
    reg = get_registry()
    for name, brick in registry._bricks.items():
        cap = getattr(brick, "capabilities", {}) or {}
        tool_fn = cap.get("agent_tools")
        if tool_fn:
            try:
                tools = tool_fn()
                for t in tools:
                    reg.register(t)
                    _LOGGER.info("从砖块 %s 加载工具 %s", name, t.name)
            except Exception as exc:
                _LOGGER.warning("从砖块 %s 加载工具失败: %s", name, exc)


# ── 启动时注册内置工具 ──────────────────────────────────────────
_ensure_tools()

# ── 角色扮演：落盘与解析 ─────────────────────────────────────

def _agent_memory_path(conversation_id: str, character_id: str = "") -> Path:
    """按会话+角色持久化记忆文件路径；净化 id 防路径穿越。

    不同角色使用不同的记忆文件，实现「人格隔离」——切换角色时不会带入
    其他角色的记忆上下文。无角色时使用默认路径。
    """
    safe_conv = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id or "default")
    if character_id:
        safe_char = re.sub(r"[^A-Za-z0-9_\-]", "_", character_id[:32])
        filename = f"{safe_char}_{safe_conv}.json"
    else:
        filename = f"{safe_conv}.json"
    return Path(settings.STORAGE_POOL_DIR) / "agent_memory" / filename


def _resolve_persona(req: AgentRunRequest) -> str:
    """解析人设文本：内置角色优先，其次直接用请求里的人设文本。"""
    if req.character_id:
        card = _roleplay().load_character(req.character_id)
        if card:
            return _roleplay().render_persona(card)
    if req.persona_text:
        return req.persona_text
    return ""


def _slugify(text: str) -> str:
    """把角色名转成可作为文件名的 id。"""
    s = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "_", text.strip())
    return s.strip("_") or "custom"


# 启动时把内置角色写入磁盘（已存在则跳过）
# 梦瑶内置角色的 Skill 文件位置：仅由环境变量 PALM_MENGYAO_SKILL_PATH 指定，
# 未设置则跳过（不再硬编码任何绝对路径，部署时按环境注入）。
_mengyao_env = os.environ.get("PALM_MENGYAO_SKILL_PATH")
if registry.get("roleplay") is not None:
    _roleplay_api = _roleplay()
    if _mengyao_env:
        _mengyao_path = Path(_mengyao_env)
        if _mengyao_path.exists():
            _roleplay_api.set_mengyao_skill_path(str(_mengyao_path))
    _roleplay_api.ensure_builtins()


# ── API 端点 ────────────────────────────────────────────────────

@router.get("/tools", dependencies=[Depends(require_api_token)])
async def list_tools():
    """返回全部已注册工具的列表（名称/描述/参数）。"""
    tools = get_registry().list_tools()
    return {
        "tools": [
            {
                "name": t.spec.name,
                "description": t.spec.description,
                "parameters": t.spec.parameters,
                "event_type": t.spec.event_type,
            }
            for t in tools
        ],
        "total": len(tools),
    }


def _resolve_settings() -> tuple[bool, bool, bool]:
    """读取 Agent 设置（联网搜索/深度思考/自动筛选工具）。
    缺省：联网开、思考关、筛选开。
    """
    is_web_search_enabled = True
    is_deep_think_enabled = False
    is_auto_filter_tools = True
    settings_brick = registry.get("settings")
    if not settings_brick:
        return (is_web_search_enabled, is_deep_think_enabled, is_auto_filter_tools)
    load_fn = (getattr(settings_brick, "capabilities", {}) or {}).get("load_app_settings")
    if not load_fn:
        return (is_web_search_enabled, is_deep_think_enabled, is_auto_filter_tools)
    try:
        app_settings = load_fn()
        is_web_search_enabled = bool(app_settings.get("agentWebSearch", True))
        is_deep_think_enabled = bool(app_settings.get("agentDeepThink", False))
        is_auto_filter_tools = bool(app_settings.get("agentAutoFilterTools", True))
    except Exception:
        pass
    return (is_web_search_enabled, is_deep_think_enabled, is_auto_filter_tools)


def _filter_web_tools(agent: Agent, is_web_search_enabled: bool) -> None:
    """联网搜索关闭时，从注册表中移除网络工具。"""
    if is_web_search_enabled:
        return
    for tool_name in ["web_search", "web_fetch"]:
        existing = agent._tools.get(tool_name)
        if existing:
            agent._tools._tools.pop(tool_name, None)


class AskResponseRequest(BaseModel):
    """用户提交 ask_user 提问的回答。"""
    question_id: str
    conversation_id: str = ""
    answer: dict = Field(default_factory=dict)


@router.post("/ask-response", dependencies=[Depends(require_api_token)])
async def agent_ask_response(req: AskResponseRequest):
    """接收用户对 ask_user 提问的回答，resolve 阻塞中的 Agent 流程。"""
    _evo = get_evolution_api()
    if _evo is not None:
        _evo.touch_activity()
    ok = get_question_hub().answer(req.question_id, req.conversation_id, req.answer)
    return {"ok": ok}


@router.post("/run", dependencies=[Depends(require_api_token)])
async def run_agent(req: AgentRunRequest):
    """运行 Agent，以 SSE 流式返回每个事件。"""
    # mock 模式（未携带真实 LLM 供应商）下禁用 Agent 执行：仅对话可用。
    if _is_mock_run(req):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "disabled": True,
                     "reason": "mock 模式已禁用 Agent 执行；仅对话可用。请在「设置 › 模型」配置真实模型供应商后启用。"},
        )
    # 看门狗：注册 agent 心跳（流式循环内每事件打点，见 _events）。
    register_heartbeat("agent")
    # 记录事件循环，供后台任务调度器跨线程唤醒 Agent（EventSource 推送用）
    try:
        _bg_scheduler().set_loop(asyncio.get_event_loop())
    except Exception:
        pass
    # 用户发消息即刷新活动时间，闲置判定据此计算。
    _evo = get_evolution_api()
    if _evo is not None:
        _evo.touch_activity()
    return StreamingResponse(
        _stream_agent_sse(req, is_wakeup=False),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _to_sse_line(event) -> str:
    return f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"


async def _merge_ask_events(main_gen, agent):
    """并发合并主事件流与 ask_user 即时队列，优先透传队列事件。

    主流在 question_hub.wait 上阻塞时（run_code 守卫/ask_user 工具），队列中的
    ask_user 事件仍能即时到达消费方；主流结束（StopAsyncIteration）即整体结束。
    """
    queue = getattr(agent, "_ask_events", None)
    if queue is None:
        async for ev in main_gen:
            yield ev
        return
    main_iter = main_gen.__aiter__()
    main_task = asyncio.ensure_future(main_iter.__anext__())
    ask_task = asyncio.ensure_future(queue.get())
    try:
        while True:
            done, _pending = await asyncio.wait(
                {main_task, ask_task}, return_when=asyncio.FIRST_COMPLETED)
            if ask_task in done:
                ask_ev = ask_task.result()
                yield ask_ev
                ask_task = asyncio.ensure_future(queue.get())
            if main_task in done:
                try:
                    main_ev = main_task.result()
                except StopAsyncIteration:
                    break
                yield main_ev
                main_task = asyncio.ensure_future(main_iter.__anext__())
    finally:
        if not main_task.done():
            main_task.cancel()
        if not ask_task.done():
            ask_task.cancel()
        await asyncio.gather(main_task, ask_task, return_exceptions=True)


def _derive_tool_mode(req: AgentRunRequest) -> str:
    provider_mode = "openai"
    if isinstance(req.provider, dict):
        provider_mode = req.provider.get("mode", "openai") or "openai"
    elif req.provider is not None and hasattr(req.provider, "mode"):
        provider_mode = getattr(req.provider, "mode", "openai") or "openai"
    tool_mode = req.tool_mode or "native"
    if tool_mode == "native" and provider_mode == "anthropic":
        tool_mode = "react"
    return tool_mode


def _create_agent(req, memory, is_deep_think_enabled, is_web_search_enabled,
                  persona_text, character_card, tool_mode, auto_filter_tools=True):
    agent = Agent(
        model=req.model,
        memory=memory,
        max_iterations=req.max_iterations,
        deep_think=is_deep_think_enabled,
        user_message=req.message,
        max_plan_steps=req.max_plan_steps,
        persona_text=persona_text,
        character_card=character_card,
        conversation_id=req.conversation_id,
        character_id=req.character_id,
        tool_mode=tool_mode,
        auto_filter_tools=auto_filter_tools,
        allowed_tools=req.allowed_tools,
    )
    _filter_web_tools(agent, is_web_search_enabled)
    return agent


def _record_usage_on_done(event, req, usage_container) -> None:
    # 展示与记账分两层：① 真实用量下发 event.usage，供前端气泡/会话条显示；
    # ② 仅真实用量落台账——估算量（is_estimate）既不下发也不记账，
    #    用户要求「不显示 mock 用量」（本地模型按字符估算的数字不是真实消耗）。
    # 估算量在 llm_bridge 已不混入容器（total<=0 时只打标记、不累加），
    # 故此处只需判断容器里是否有真实总量。
    is_estimate = usage_container.pop("is_estimate", False)
    usage_payload = dict(usage_container)
    total = usage_payload.get("total_tokens", 0) or 0
    if is_estimate or total <= 0:
        # 无真实用量：不下发数字（前端不显示 mock），不落台账
        event.usage = {} if not total else usage_payload
        return
    event.usage = usage_payload
    usage_brick = registry.get("usage")
    record_fn = (getattr(usage_brick, "capabilities", {}) or {}).get("record_usage") if usage_brick else None
    if not record_fn:
        return
    p = req.provider
    provider_name = ""
    if isinstance(p, dict):
        provider_name = p.get("provider") or ""
    elif p is not None and hasattr(p, "provider") and p.provider:
        provider_name = p.provider
    if not provider_name and "/" in req.model:
        provider_name = req.model.split("/", 1)[0]
    record_fn(
        chat_id=req.conversation_id or "",
        model=req.model,
        provider=provider_name,
        prompt_tokens=usage_payload.get("prompt_tokens", 0),
        completion_tokens=usage_payload.get("completion_tokens", 0),
        total_tokens=total,
    )


def _award_game_xp_on_done(event, req, usage_container) -> None:
    """对话结束在后端落账经验与星砂（经 game 砖 capability，缺失降级跳过）。

    仅用户轮触发（is_wakeup 不结算，与旧前端兜底一致），避免唤醒轮重复计数。
    经验与星砂由 game 砖结算；game 砖缺失或未注册能力时静默跳过，绝不阻断对话本身。
    """
    token_count = int(usage_container.get("total_tokens", 0) or 0)
    affinity = float(getattr(event, "affinity", None) or 0.0)
    affinity_state = getattr(event, "affinity_state", None)
    dynamics = 0.0
    if isinstance(affinity_state, dict):
        dynamics = float(affinity_state.get("dynamics", 0.0) or 0.0)
    try:
        game_brick = registry.get("game")
        caps = getattr(game_brick, "capabilities", {}) or {}
        # 聊天经验+星砂：仅用户轮且有真实用量时结算
        if token_count > 0:
            award_chat = caps.get("award_chat_xp")
            if award_chat:
                award_chat(token_count, affinity, dynamics)
        # 自动规划任务：开启自动规划即视为触发一次 plan_once（含星砂）
        if getattr(req, "use_planning", False):
            award_plan = caps.get("award_plan_xp")
            if award_plan:
                award_plan()
    except Exception as exc:
        _LOGGER.warning("经验结算失败（已跳过，不影响对话）: %s", exc)


def _prepare_agent_run(req: AgentRunRequest, is_wakeup: bool):
    # 唤醒轮 contextvar：供 start_background_task 工具检测套娃并拒绝再登记
    from .tool_base import agent_is_wakeup
    agent_is_wakeup.set(is_wakeup)

    # 裁决引擎砖已拆：安全门统一走 palm_sdk.guardrail（与 adjudicator_cap 接口一致）。
    adj_check = get_guardrail_capability()
    (is_web_search_enabled, is_deep_think_enabled, is_auto_filter_tools) = _resolve_settings()

    persona_text = _resolve_persona(req)
    character_card = _roleplay().load_character(req.character_id) if req.character_id else None
    memory = _memory().Memory(
        persist_path=str(_agent_memory_path(req.conversation_id, req.character_id)),
        vector_persist_dir=str(
            Path(settings.STORAGE_POOL_DIR) / "vector_memory"
            / (req.character_id or "default")
        ),
        character_card=character_card,
        conversation_id=req.conversation_id,
    )
    tool_mode = _derive_tool_mode(req)
    agent = _create_agent(
        req, memory, is_deep_think_enabled, is_web_search_enabled,
        persona_text, character_card, tool_mode, is_auto_filter_tools,
    )
    usage_container: dict = {}
    provider_raw = req.provider

    # 透传当前供应商配置给 automation 砖 worker（其自带 LLM 复用同一模型供应商）。
    from .tool_base import agent_provider
    agent_provider.set(provider_raw)

    async def _llm_with_provider(messages, model, tools=None):
        async for chunk in _stream_llm(messages, model, provider_raw, usage_container, tools=tools):
            yield chunk

    return memory, agent, _llm_with_provider, usage_container, adj_check


async def _stream_agent_sse(req: AgentRunRequest, is_wakeup: bool = False) -> AsyncIterator[str]:
    """构建 Agent 并把事件流包装为 SSE 行。复用于正常对话与后台任务唤醒。

    is_wakeup=True 时标记唤醒轮：① 禁止再登记后台任务（套娃防护）；
    ② 跳过好感度调整（避免系统提醒文本污染好感度启发式）。
    """
    memory, agent, llm_closure, usage_container, adj_check = _prepare_agent_run(req, is_wakeup)
    # 即时事件队列必须在 agent.run 惰性执行前挂好（run 体内只补建不覆盖），
    # 否则 _merge_ask_events 在 run 未起步时取到 None 会静默退化为旧路径（死锁重现）。
    agent._ask_events = asyncio.Queue()

    final_text: list[str] = []
    affinity_emitted = False

    async def _events():
        # 即时事件通道：ask_user 弹窗等需人工介入的事件在 wait 前已进 agent._ask_events，
        # 主事件流仍在等待回答（阻塞），必须并发消费队列才能把事件即时下发、让前端应答。
        async for event in _merge_ask_events(agent.run(
            req.message, llm_closure, adj_check,
            use_planning=req.use_planning,
            structured_output=req.structured_output,
        ), agent):
            _wd_touch("agent")  # 看门狗心跳：每事件打点，卡死可被检测
            yield event

    try:
        yield _to_sse_line(AgentEvent(type="thought", content=""))
        try:
            await memory.initialize()
        except Exception as exc:
            _LOGGER.warning("记忆初始化失败（继续运行）: %s", exc)
        async for event in _events():
            if event.type == "done" and usage_container and usage_container.get("total_tokens", 0) > 0:
                _record_usage_on_done(event, req, usage_container)
            if event.type == "delta":
                final_text.append(event.content)
            if event.type == "done" and not affinity_emitted:
                affinity_emitted = True
                # 唤醒轮不调整好感度，避免系统提醒文本污染
                if not is_wakeup:
                    affinity_result = memory.core.settle_affinity_from_model("".join(final_text))
                    # 大幅涨/跌 → 记一条带重要度的情感事件到记忆层（幂律关键字复苏）
                    _record_emotion_event(memory, affinity_result, req.message)
                    event.affinity = affinity_result.get("base", memory.get_affinity())
                    event.affinity_state = affinity_result
                    # 后端落账经验与星砂（替代旧前端兜底，避免跨端丢失/重复计数）
                    _award_game_xp_on_done(event, req, usage_container)
                await memory.shutdown()
            yield _to_sse_line(event)
    except Exception as exc:
        try:
            await memory.shutdown()
        except Exception:
            pass
        err = AgentEvent(type="error", content=str(exc))
        yield _to_sse_line(err)
    finally:
        try:
            get_question_hub().cancel_for_conversation(req.conversation_id)
        except Exception:
            pass




def _record_emotion_event(memory, affinity_result: dict, user_message: str) -> None:
    """大幅好感度波动时，记一条带重要度的情感事件到记忆层。

    复用记忆层幂律衰减（archived_memory）：以后聊到关键词时，由衰减公式决定
    该暖心/扎心瞬间是否还"鲜活"、值得主动提起，从而让好感度带情感记忆沉淀，
    而非冷冰冰的计数器。仅显著波动才记，避免记忆污染。
    """
    try:
        raw_base = float(affinity_result.get("raw_base_delta", 0.0) or 0.0)
        raw_dyn = float(affinity_result.get("raw_dyn_delta", 0.0) or 0.0)
        magnitude = abs(raw_base) + abs(raw_dyn)
        if magnitude < 3.0:
            return  # 仅显著波动才沉淀为情感记忆
        # 重要度随波动幅度上升（3~10），日记式语义便于后续关键词复苏
        importance = min(10, max(3, int(magnitude)))
        if raw_base + raw_dyn < 0:
            content = f"用户曾说：「{user_message[:40]}」——那一刻关系明显受挫（好感度回落）。"
        else:
            content = f"用户曾说：「{user_message[:40]}」——那一刻关系明显升温（好感度提升）。"
        memory.archived.add(content, importance=importance)
    except Exception as exc:
        _LOGGER.debug("情感事件记录失败（非致命）: %s", exc)


@router.get("/events", dependencies=[Depends(require_api_token)])
async def agent_events(conversation_id: str = ""):
    """前端订阅：后台任务完成后，即便用户未发新消息也能收到 AI 自动唤醒的回复流。"""
    q = _bg_scheduler().subscribe(conversation_id)

    async def event_stream():
        try:
            while True:
                line = await q.get()
                yield line
        except asyncio.CancelledError:
            # 订阅断开即清理，避免队列泄漏
            _bg_scheduler().unsubscribe(conversation_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 砖块注册 ─────────────────────────────────────────────────────

# ── 角色扮演 API ────────────────────────────────────────────────

@router.get("/characters", dependencies=[Depends(require_api_token)])
async def get_characters():
    """列出全部角色（id / name / tagline）。"""
    return {"characters": _roleplay().list_characters()}


@router.get("/characters/{character_id}", dependencies=[Depends(require_api_token)])
async def get_character(character_id: str):
    """获取单个角色卡片完整内容。"""
    card = _roleplay().load_character(character_id)
    if not card:
        return {"error": f"角色不存在：{character_id}"}
    return card.to_dict()


@router.post("/characters", dependencies=[Depends(require_api_token)])
async def create_character(payload: dict):
    """创建/覆盖一个角色卡片。"""
    card = _roleplay().CharacterCard.from_dict(payload)
    if not card.id:
        card.id = _slugify(card.name)
    _roleplay().save_character(card)
    return card.to_dict()


@router.post("/characters/import", dependencies=[Depends(require_api_token)])
async def import_character(payload: dict):
    """从 Markdown 格式的 Skill 文本导入角色卡片。"""
    text = payload.get("text", "")
    if not text.strip():
        return {"error": "内容不能为空"}
    card_id = payload.get("id") or None
    card = _roleplay().import_from_markdown(text, card_id)
    return card.to_dict()


@router.get("/affinity", dependencies=[Depends(require_api_token)])
async def get_affinity(conversation_id: str = ""):
    """读取某会话的当前好感度（双线：base/dynamics/bond + 档名）。

    数值默认对所有前台隐藏；仅当好感度显示道具（affinity_display）已解锁时，
    display_allowed=True，前端方可渲染数值/阶段名（道具开关的权威来源在后端）。
    """
    if not conversation_id:
        return {"affinity": 0.0, "display_allowed": False}
    cm = _memory().CoreMemory(str(_agent_memory_path(conversation_id)))
    await cm.initialize()
    st = cm.get_affinity_state()
    # 道具开关：经 game 砖 capability 查询，缺失降级 False（保持隐藏）。
    display_allowed = False
    try:
        game_brick = registry.get("game")
        has_fn = (getattr(game_brick, "capabilities", {}) or {}).get("has_item")
        if has_fn:
            display_allowed = bool(has_fn("affinity_display"))
    except Exception:
        display_allowed = False
    # 好感度数值仅在道具解锁后对外暴露；否则仅给档名（不露数值）。
    stage_name = ""
    try:
        rs = _affinity().resolve_ruleset(cm._character_card)
        tier = rs.match_base_tier(float(st.get("base", 0.0)))
        stage_name = tier.name
    except Exception:
        stage_name = ""
    result = {
        "conversation_id": conversation_id,
        "affinity": st.get("base", 0.0),
        "dynamics": st.get("dynamics", 0.0),
        "bond": st.get("bond", 0.0),
        "stage_name": stage_name,
        "display_allowed": display_allowed,
    }
    return result


@router.post("/affinity", dependencies=[Depends(require_api_token)])
async def set_affinity(payload: dict):
    """直接设定某会话的好感度（绝对值，clamp ±100）。"""
    conversation_id = payload.get("conversation_id", "")
    if not conversation_id:
        return {"error": "缺少 conversation_id"}
    try:
        value = float(payload.get("value", 0.0))
    except (TypeError, ValueError):
        return {"error": "value 必须是数字"}
    cm = _memory().CoreMemory(str(_agent_memory_path(conversation_id)))
    await cm.initialize()
    cm.set_affinity(value)
    await cm.shutdown()
    return {"conversation_id": conversation_id, "affinity": cm.affinity}


def _purge_conversation_memory(conversation_id: str) -> str:
    # 记忆为每会话单文件（{角色}_{会话}.json 或 {会话}.json），按文件名定位删除；
    # 向量记忆按角色共享，需逐集合按 conv_id 清理（A2 之后落盘的条目生效）。
    safe_conv = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id or "default")
    mem_dir = Path(settings.STORAGE_POOL_DIR) / "agent_memory"
    removed = 0
    if mem_dir.is_dir():
        for p in mem_dir.glob("*.json"):
            name = p.name
            if name == f"{safe_conv}.json" or name.endswith(f"_{safe_conv}.json"):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    try:
        removed += _memory().purge_vector_by_conv_id(conversation_id)
    except Exception:  # noqa: BLE001
        pass
    return f"conversation {conversation_id}: 清理 {removed} 项记忆/向量"


def _purge_character_memory(character_id: str) -> str:
    # 删除该角色的全部会话记忆文件（{角色}_*.json）及其共享向量目录，避免亲和力/向量孤儿。
    safe_char = re.sub(r"[^A-Za-z0-9_\-]", "_", character_id[:32])
    mem_dir = Path(settings.STORAGE_POOL_DIR) / "agent_memory"
    removed = 0
    if mem_dir.is_dir():
        for p in mem_dir.glob(f"{safe_char}_*.json"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    vec_dir = Path(settings.STORAGE_POOL_DIR) / "vector_memory" / character_id
    if vec_dir.is_dir():
        shutil.rmtree(vec_dir, ignore_errors=True)
        removed += 1
    return f"character {character_id}: 清理 {removed} 项记忆/向量"


def _purge_character_habits(character_id: str) -> None:
    # 删除角色时连带清理其习惯推断账本，避免孤儿状态（与记忆/向量同级联）。
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in (character_id or "default"))[:32]
    p = Path(settings.STORAGE_POOL_DIR) / "agent_habits" / f"{safe}.json"
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def _handle_entity_deleted(entity_type: str, entity_id: str) -> str:
    # 作为 capabilities["on_entity_deleted"] 被协调器扇出调用；只清理 agent 自身引用。
    if entity_type == ENTITY_CONVERSATION:
        return _purge_conversation_memory(entity_id)
    if entity_type == ENTITY_CHARACTER:
        _purge_character_memory(entity_id)
        _purge_character_habits(entity_id)
        return "ok"
    return "ignored"


@router.delete("/characters/{character_id}", dependencies=[Depends(require_api_token)])
async def delete_character(character_id: str):
    # 删除角色卡片并扇出事件，连带清理该角色关联的 agent 记忆与向量（防止亲和力孤儿）。
    card_path = Path(settings.STORAGE_POOL_DIR) / "characters" / f"{character_id}.json"
    if not card_path.exists():
        return {"deleted": False, "reason": "角色不存在"}
    try:
        card_path.unlink()
    except OSError:
        return {"deleted": False, "reason": "卡片删除失败"}
    emit_entity_deleted(ENTITY_CHARACTER, character_id)
    return {"deleted": True}


def push_bubble(conversation_id: str, text: str) -> None:
    # 经 evolution 砖持有的调度单例把文本作为助手气泡（delta+done）推到会话队列。
    # 气泡的 SSE 序列化与 AgentEvent 由本砖负责，evolution 经本能力回调，零反向 import。
    try:
        _bg_scheduler().push_event(
            conversation_id, _to_sse_line(AgentEvent(type="delta", content=text)))
        _bg_scheduler().push_event(
            conversation_id, _to_sse_line(AgentEvent(type="done", content=text)))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("推送气泡失败（会话 %s）: %s", conversation_id, exc)


def run_proactive_stream(req_dict: dict, is_wakeup: bool = False):
    # 供 evolution 砖经 capability 调用的流式推送入口：构造请求并产出 SSE 行。
    # req_dict 为 AgentRunRequest 字段字典，避免 evolution 反向 import agent 的 schema。
    req = AgentRunRequest(**req_dict)
    return _stream_agent_sse(req, is_wakeup=is_wakeup)


# ── 双模认知引擎入口（Reflex-Cortex） ───────────────────────────

@router.post("/dual-run", dependencies=[Depends(require_api_token)])
async def run_dual_agent(req: AgentRunRequest):
    """双模认知引擎运行入口：Boss 直答 + Worker 后台深度执行。

    与 /run 的区别：消息先经 IntentRouter 路由，
    闲聊由 Boss 直答，复杂任务后台启动 Worker，用户可实时干预。
    """
    # mock 模式（未携带真实 LLM 供应商）下禁用 Agent 执行：仅对话可用。
    if _is_mock_run(req):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "disabled": True,
                     "reason": "mock 模式已禁用 Agent 执行；仅对话可用。请在「设置 › 模型」配置真实模型供应商后启用。"},
        )
    register_heartbeat("agent")
    try:
        _bg_scheduler().set_loop(asyncio.get_event_loop())
    except Exception:
        pass
    _evo = get_evolution_api()
    if _evo is not None:
        _evo.touch_activity()
    return StreamingResponse(
        _stream_dual_sse(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dual-status", dependencies=[Depends(require_api_token)])
async def dual_status(conversation_id: str = ""):
    """查询双模引擎状态：Worker 是否活跃、轨迹条数、任务目标。"""
    coord = _dual_coordinators.get(conversation_id)
    if coord is None:
        return {
            "worker_active": False,
            "worker_finished": False,
            "task_started": False,
            "trace_entries": 0,
            "task_goal": "",
            "last_trace_type": "",
        }
    return coord.get_status()


@router.post("/dual-intervene", dependencies=[Depends(require_api_token)])
async def dual_intervene(payload: dict):
    """手动干预 Worker：action=cancel/pause/resume/redirect。"""
    conversation_id = payload.get("conversation_id", "")
    action = payload.get("action", "")
    instruction = payload.get("instruction", "")
    coord = _dual_coordinators.get(conversation_id)
    if coord is None:
        return {"ok": False, "reason": "无活跃协调器"}
    ok = coord.intervene(action, instruction)
    return {"ok": ok}


# 会话级协调器缓存（conversation_id → DualCoordinator）
_dual_coordinators: dict[str, object] = {}


async def _stream_dual_sse(req: AgentRunRequest) -> AsyncIterator[str]:
    """双模协调器 SSE 流：意图路由 → Boss/Worker 分发。"""
    from .dual.coordinator import DualCoordinator

    # 复用现有依赖获取逻辑（memory / llm_closure / adj_check）
    memory, _orig_agent, llm_closure, usage_container, adj_check = _prepare_agent_run(req, False)
    persona_text = _resolve_persona(req)
    character_card = _roleplay().load_character(req.character_id) if req.character_id else None

    # 创建或复用协调器（同一会话保持 Boss 常驻）
    coord = _dual_coordinators.get(req.conversation_id)
    if coord is None:
        coord = DualCoordinator(
            boss_model=req.model,
            worker_model=req.model,  # 暂与 Boss 同模型，后续可配置独立 worker_model
            llm_stream_fn=llm_closure,
            adjudicator_check_fn=adj_check,
            conversation_id=req.conversation_id,
            character_id=req.character_id,
            persona_text=persona_text,
            character_card=character_card,
            boss_memory=memory,
            vector_persist_dir=str(
                Path(settings.STORAGE_POOL_DIR) / "vector_memory"
                / (req.character_id or "default")
            ),
        )
        _dual_coordinators[req.conversation_id] = coord

    # Boss 需要预挂 ask_events 队列（与 _stream_agent_sse 对齐，防死锁）
    coord._boss._ask_events = asyncio.Queue()

    try:
        yield _to_sse_line(AgentEvent(type="thought", content=""))
        try:
            await memory.initialize()
        except Exception as exc:
            _LOGGER.warning("记忆初始化失败（继续运行）: %s", exc)

        final_text: list[str] = []
        async for event in coord.handle_message(req.message):
            _wd_touch("agent")
            if event.type == "done" and usage_container and usage_container.get("total_tokens", 0) > 0:
                _record_usage_on_done(event, req, usage_container)
            if event.type == "delta":
                final_text.append(event.content)
            yield _to_sse_line(event)
    except Exception as exc:
        try:
            await memory.shutdown()
        except Exception:
            pass
        err = AgentEvent(type="error", content=str(exc))
        yield _to_sse_line(err)
    finally:
        try:
            get_question_hub().cancel_for_conversation(req.conversation_id)
        except Exception:
            pass


# 门面：暴露本砖包对象供其它砖经 capability 取用（run_proactive_stream / push_bubble 等）。
# 砖间零互导，evolution 经此回调，避免反向 import agent 内部 schema（如 AgentRunRequest）。
agent_api = sys.modules[__package__]

brick = Brick(
    manifest=BrickManifest(
        name="agent",
        title="Agent 框架",
        description="可换记忆 × 可扩工具 × 裁决引擎护航的 Agent 框架。默认开启自主规划引擎（先制定计划、分步执行、失败自动重规划），支持 ReAct 循环、内置工具集、运行时工具注册。",
        bus_type="cpu",
        is_streaming=True,
    ),
    router=router,
    permissions=[
        PermissionSpec(key="sandbox.run_code", title="执行代码（沙箱隔离）",
                        description="在隔离沙箱中执行 Python/Node/Shell 代码，可能调用系统资源或网络。",
                        risk=RiskLevel.HIGH, brick="agent"),
        PermissionSpec(key="desktop.control", title="桌面自动化控制",
                        description="模拟键盘、鼠标、剪贴板与截图，可直接操作用户当前桌面。",
                        risk=RiskLevel.HIGH, brick="agent"),
        PermissionSpec(key="network.http_outbound", title="对外网络访问",
                        description="联网搜索、网页抓取与在线查询（如汉字百科），会向外部站点发起请求。",
                        risk=RiskLevel.MEDIUM, brick="agent"),
        PermissionSpec(key="system.restore", title="创建/清理系统还原点",
                        description="创建或清理 Windows 系统还原点（系统级操作，不保护个人文件）。",
                        risk=RiskLevel.HIGH, brick="agent"),
    ],
    capabilities={
        "agent_tools": lambda: get_registry().list_tools(),
        "register_tool": lambda t: get_registry().register(t),
        # 注销工具：self_evolution 砖经此把被禁用的自注册工具从运行期工具表移除。
        "unregister_tool": lambda name: get_registry().unregister(name),
        # 门面：供 evolution 砖经 get_agent_api() 取用 run_proactive_stream / push_bubble。
        "agent_api": agent_api,
        # 流式推送入口：evolution 砖经此让 agent 生成内容并产出 SSE 行（构造 AgentRunRequest）。
        "run_proactive_stream": run_proactive_stream,
        # 气泡推送：evolution 经此把文本作为助手气泡投到会话队列（SSE 序列化在本砖）。
        "push_bubble": push_bubble,
        # 记忆文件路径：evolution（offline_digest）经此取会话记忆落盘路径。
        "memory_path": _agent_memory_path,
        # 声明级联删除钩子：协调器扇出事件时清理 agent 自身对该实体的引用。
        "on_entity_deleted": _handle_entity_deleted,
    },
)
registry.register(brick)