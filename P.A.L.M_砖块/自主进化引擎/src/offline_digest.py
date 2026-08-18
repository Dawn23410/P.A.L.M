"""每日偏好简报：复用 scheduler 砖定时触发，用 Flash 模型压缩近期记忆为 300 字中文简报。

设计要点（源自自主进化架构决策）：
- 复用既有 scheduler 砖的 cron（每日低峰 0 4 * * *），不新写定时逻辑。
- 简报写入持久化向量记忆（ArchivedMemory 为纯内存壳不落盘，故读取/写回都走 VectorMemory），
  **不新建 belief_state.json**（避免孤儿状态，呼应级联删除契约）。
- 简报语言定中文（融入中文记忆体系更连贯）。
- LLM 调用经 models 砖 create_stream（一次性摘要，非 Agent，省开销）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from palm_sdk.bricks.base import registry
from palm_sdk.core.config import settings

# 摘要任务哨兵：_run_proactive 据此把任务路由到本模块而非通用推送。
DIGEST_SENTINEL = "__DIGEST__::"
# 摘要落地的系统会话/角色（独立于用户会话，避免污染真实对话记忆）。
DIGEST_CONV = "__digest__"
DIGEST_CHAR = ""
DIGEST_JOB_TITLE = "每日偏好简报"
DIGEST_CRON = "0 4 * * *"


def _load_settings() -> dict:
    brick = registry.get("settings")
    if not brick:
        return {}
    fn = (getattr(brick, "capabilities", {}) or {}).get("load_app_settings")
    if not fn:
        return {}
    try:
        return fn() or {}
    except Exception:
        return {}


def _build_digest_prompt(recent_text: str) -> str:
    # 把近期记忆片段压成高密度「用户偏好简报」指令（中文、限 300 字）。
    return (
        "以下是用户近期的记忆片段，请用不超过 300 个汉字，提炼成一份"
        "「用户偏好简报」（高密度、纯事实、便于后续对话复用）：\n\n" + recent_text
    )


async def _summarize(model: str, prompt: str) -> str:
    # 经 models 砖 create_stream 一次性摘要（非 Agent，省开销）；失败返回空串。
    models_brick = registry.get("models")
    if not models_brick:
        return ""
    stream_fn = (getattr(models_brick, "capabilities", {}) or {}).get("create_stream")
    if not stream_fn:
        return ""
    parts: list[str] = []
    msg = SimpleNamespace(role="user", content=prompt)
    try:
        async for delta in stream_fn([msg], model=model or "mock"):
            text = getattr(delta, "content", "") or ""
            if text:
                parts.append(text)
    except Exception:
        return ""
    return "".join(parts).strip()


async def run_digest(
    conversation_id: str,
    character_id: str,
    model: str,
    summarizer=None,
) -> str:
    # 读取近期记忆 → 摘要 → 写回持久化向量记忆。summarizer 供测试注入。
    from palm_sdk.bricks._shared.paths import agent_memory_path
    from palm_sdk.bricks._shared.interop import get_memory_api

    mem_api = get_memory_api()
    if mem_api is None:
        return ""
    path = str(agent_memory_path(conversation_id, character_id))
    vec_dir = str(
        Path(settings.STORAGE_POOL_DIR) / "vector_memory" / (character_id or "default")
    )
    mem = mem_api.Memory(
        persist_path=path,
        vector_persist_dir=vec_dir,
        character_card=None,
        conversation_id=conversation_id,
    )
    try:
        await mem.initialize()
        # 修复点：长期记忆跨进程持久落在 VectorMemory（ChromaDB），ArchivedMemory 是
        # 纯内存壳不落盘；若从空壳 archived 读取，每日简报在真实部署中恒为空、永不生成。
        # 改为从持久化向量读取近期记忆，并把简报写回向量（持久且供次日简报累积复用）。
        recent_items = mem.vector.get_recent(limit=30, skip_kind="digest")
        recent = "\n".join(it["content"] for it in recent_items)
        if not recent.strip():
            return ""
        prompt = _build_digest_prompt(recent)
        summary = summarizer(prompt) if summarizer else await _summarize(model, prompt)
        if summary and mem.vector.is_ready:
            mem.vector.add(
                summary,
                metadata={"role": "system", "importance": 5,
                          "conv_id": conversation_id, "kind": "digest"},
            )
            return summary
    finally:
        await mem.shutdown()
    return ""


def register_daily_digest() -> None:
    # 经 scheduler 砖能力注册每日摘要任务（幂等：同名任务已存在则跳过）。
    scheduler_brick = registry.get("scheduler")
    if not scheduler_brick:
        return
    create_fn = (getattr(scheduler_brick, "capabilities", {}) or {}).get("create_job")
    if not create_fn:
        return
    try:
        store = (getattr(scheduler_brick, "capabilities", {}) or {}).get("list_jobs")
        if store:
            existing = [j for j in store() if j.get("title") == DIGEST_JOB_TITLE]
            if existing:
                return
        flash = _load_settings().get("flashModel") or ""
        create_fn(
            conversation_id=DIGEST_CONV,
            character_id=DIGEST_CHAR,
            model=flash,
            title=DIGEST_JOB_TITLE,
            brief=DIGEST_SENTINEL + "生成并保存今日偏好简报",
            schedule_type="cron",
            schedule_value=DIGEST_CRON,
        )
    except Exception:
        # 注册失败不阻断主流程（下次主动推送时再试）。
        pass