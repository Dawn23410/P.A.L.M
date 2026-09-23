"""会话历史的 JSON 持久化：CRUD 与导出/导入。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import List, Optional

from .config import CONV_DIR
from .models import Conversation, Message


def _conv_path(cid: str) -> Path:
    return CONV_DIR / f"{cid}.json"


def list_conversations() -> List[dict]:
    convs: List[dict] = []
    if not CONV_DIR.exists():
        return convs
    for f in CONV_DIR.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        convs.append({
            "id": raw.get("id", f.stem),
            "title": raw.get("title", "新对话"),
            "created_at": raw.get("created_at", 0),
            "updated_at": raw.get("updated_at", 0),
            "message_count": len(raw.get("messages", [])),
        })
    convs.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return convs


def get_conversation(cid: str) -> Optional[Conversation]:
    p = _conv_path(cid)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return Conversation.model_validate(raw)


def create_conversation(title: str = "新对话") -> Conversation:
    now = time.time()
    conv = Conversation(
        id=uuid.uuid4().hex[:12],
        title=title,
        created_at=now,
        updated_at=now,
        messages=[],
    )
    save_conversation(conv)
    return conv


def save_conversation(conv: Conversation) -> None:
    conv.updated_at = time.time()
    # 加固：不假设调用方已跑过 ensure_dirs()（包模式直接调 run_chat 时目录可能不存在）
    _conv_path(conv.id).parent.mkdir(parents=True, exist_ok=True)
    _conv_path(conv.id).write_text(
        conv.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )


def delete_conversation(cid: str) -> bool:
    p = _conv_path(cid)
    if p.exists():
        p.unlink()
        return True
    return False


def append_message(cid: str, msg: Message) -> Optional[Conversation]:
    conv = get_conversation(cid)
    if conv is None:
        return None
    if msg.ts is None:
        msg.ts = time.time()
    # 若首条用户消息且无标题，用之生成标题
    if conv.title == "新对话" and msg.role == "user" and msg.content:
        conv.title = msg.content[:30] + ("…" if len(msg.content) > 30 else "")
    conv.messages.append(msg)
    save_conversation(conv)
    return conv


def export_conversation(cid: str, fmt: str = "json") -> Optional[str]:
    conv = get_conversation(cid)
    if conv is None:
        return None
    if fmt == "md":
        lines = [f"# {conv.title}", "", f"> 导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for m in conv.messages:
            role = {"user": "用户", "assistant": "助手", "system": "系统"}.get(m.role, m.role)
            lines.append(f"## {role}")
            lines.append("")
            lines.append(m.content or "")
            lines.append("")
        return "\n".join(lines)
    return conv.model_dump_json(indent=2, exclude_none=False)


def import_conversation(raw_text: str) -> Optional[Conversation]:
    try:
        raw = json.loads(raw_text)
    except Exception:
        return None
    conv = Conversation.model_validate(raw)
    # 若 id 冲突则重新生成
    if _conv_path(conv.id).exists():
        conv.id = uuid.uuid4().hex[:12]
    save_conversation(conv)
    return conv
