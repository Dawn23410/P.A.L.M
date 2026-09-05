"""对话调度：组装消息、调用 provider、流式输出、落盘。"""
from __future__ import annotations

import base64
import mimetypes
import time
from typing import AsyncIterator, Optional

from .config import UPLOAD_DIR, get_provider, load_config
from .models import ChatRequest, Message, ModelParameters
from .providers import get_provider_instance
from . import storage


def resolve_image(url: Optional[str]) -> str:
    """将本地上传路径 (/uploads/xxx) 转换为自包含的 data URI，便于模型 API 直接读取。"""
    if url and url.startswith("/uploads/"):
        path = UPLOAD_DIR / url[len("/uploads/"):]
        if path.exists():
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            b64 = base64.b64encode(path.read_bytes()).decode()
            return f"data:{mime};base64,{b64}"
    return url or ""


async def run_chat(req: ChatRequest) -> AsyncIterator[dict]:
    """执行一次流式对话，产出 SSE 事件字典并持久化消息。"""
    cfg = load_config()

    # 1. 解析 provider / model / 参数
    provider_cfg = get_provider(req.provider) or get_provider(cfg.active_provider)
    if provider_cfg is None:
        yield {"type": "error", "message": "未配置有效的模型提供方，请在设置中添加。"}
        return
    model = req.model or cfg.active_model or ""
    if not model:
        yield {"type": "error", "message": "未指定模型，请在设置中选择。"}
        return
    params: ModelParameters = req.parameters or cfg.parameters
    system_prompt = req.system_prompt if req.system_prompt is not None else cfg.system_prompt

    # 2. 获取/创建会话
    if req.conversation_id:
        conv = storage.get_conversation(req.conversation_id)
        if conv is None:
            conv = storage.create_conversation()
    else:
        conv = storage.create_conversation()

    # 先告知前端会话 id（新建会话时需要）
    yield {"type": "meta", "conversation_id": conv.id, "title": conv.title}

    # 3. 追加用户消息并持久化
    user_msg = Message(role="user", content=req.content, images=req.images, ts=time.time())
    # append_message 会重新从磁盘读取并写回；用其返回值刷新内存中的 conv，
    # 否则新建会话的首条用户消息不会进入后续组装的 messages（影响模型上下文）。
    conv = storage.append_message(conv.id, user_msg) or conv

    # 4. 组装完整消息（动态注入系统提示词，并将本地图片转为 data URI）
    msgs: list[Message] = []
    if system_prompt:
        msgs.append(Message(role="system", content=system_prompt))
    for m in conv.messages:
        images = [resolve_image(i) for i in (m.images or [])] if m.images else None
        msgs.append(Message(role=m.role, content=m.content, images=images, ts=m.ts))

    # 5. 调用 provider 流式生成
    provider = get_provider_instance(provider_cfg)
    accumulated = ""
    reasoning_acc = ""
    try:
        async for chunk in provider.complete(msgs, params, model, stream=True):
            if "reasoning" in chunk:
                reasoning_acc += chunk["reasoning"]
                yield {"type": "reasoning", "content": chunk["reasoning"]}
            elif "content" in chunk:
                accumulated += chunk["content"]
                yield {"type": "token", "content": chunk["content"]}
            elif chunk.get("done"):
                yield {"type": "done", "usage": chunk.get("usage", {})}
    except Exception as e:  # 捕获所有异常，转为前端可显示的错误
        yield {"type": "error", "message": str(e)}
        return

    # 6. 落盘助手回复（含思维链，便于后续查看/导出）
    storage.append_message(
        conv.id,
        Message(role="assistant", content=accumulated, reasoning=reasoning_acc or None, ts=time.time()),
    )
    yield {"type": "meta", "conversation_id": conv.id, "title": conv.title, "finished": True}
