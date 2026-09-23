"""Anthropic 原生线格式 ↔ 内核格式的双向转换。

单独成文件的理由：这一层是**结构级**翻译（块生命周期、system 外提、tool_use/tool_result
成对出现），与 provider 的传输职责（端点、鉴权、重试、降级）是两件事。混在一个文件里
会同时突破 500 行上限并让"传输出错"和"翻译出错"难以区分。

四类映射
--------
1. **消息**：`role="tool"` → user + `tool_result` 块；system 外提到顶层；连续同角色合并。
2. **声明**：工具 `parameters` → `input_schema`；`tool_choice` 的 `required` → `any`。
3. **流式**：`message_start/message_delta` 拆输入输出侧 usage；
   `content_block_*` 三件套 → 正文/思考/工具参数分片；`signature_delta` 单独留存。
4. **结束**：`stop_reason` 映射到 OpenAI 口径，并结算统一回传字段。

思考块回传（双向）
------------------
原生协议要求多轮把上一轮助手消息的思考块**原样**送回（带签名，否则 400）。内核侧
只认自己的字段，故本层做一次往返：响应方向把原生块序列整体存进 `stats.extra.native_blocks`
（不透明字符串），请求方向若发现上一轮留下了该凭据就整条原样复活。
只存"思考块"而不存整条的理由见 `_echo_blocks`。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..models import Tool
from ._telemetry import Meter, map_stop_reason, usage_from

# 思考块签名的分隔符：多块时按顺序拼接，回传时需原样还原顺序
SIG_SEP = "\x00"

# 需要整条原样回传的原生块类型：签名/加密数据无法从内核字段重建
_ECHO_TYPES = ("thinking", "redacted_thinking")

_TOOL_CHOICE = {"auto": {"type": "auto"}, "none": {"type": "none"},
                "required": {"type": "any"}}


# ─────────────────────────── 请求方向：内核 → 原生 ───────────────────────────
async def to_native_messages(messages, fetch_image, echo_reasoning: bool = False
                             ) -> tuple[str, list[dict]]:
    """(system 文本, 原生 messages)。

    system 必须外提 —— 原生协议里没有 system 角色；`role="tool"` 是 user + tool_result 块。

    `echo_reasoning` 只在**本次请求带 tools** 时为真：官方口径是"带思考用工具时回传思考块
    才严格必需"，其余场景省略即可 —— 而 keep-all 模型上回传的历史思考会被计入输入
    token 持续计费，白付钱。故按需回传而非一概回传。
    """
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        role = getattr(m, "role", "user")
        if role == "system":
            if getattr(m, "content", ""):
                system_parts.append(m.content)
            continue
        blocks = await _blocks_for(m, fetch_image, echo_reasoning)
        if blocks:
            _append_native(out, "assistant" if role == "assistant" else "user", blocks)
    return "\n\n".join(system_parts), out


def _append_native(out: list, role: str, blocks: list) -> None:
    """连续同角色合并成一条 —— 原生协议要求 user/assistant 严格交替。"""
    if out and out[-1]["role"] == role:
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": role, "content": blocks})


async def _blocks_for(m, fetch_image, echo_reasoning: bool = False) -> list:
    """单条内核 Message → 原生 content blocks。"""
    role = getattr(m, "role", "user")
    if role == "tool":
        block = {"type": "tool_result",
                 "tool_use_id": getattr(m, "tool_call_id", "") or "",
                 "content": getattr(m, "content", "") or ""}
        if getattr(m, "tool_error", False):
            block["is_error"] = True      # 官方建议工具失败时置真，否则模型无法区分成败
        return [block]
    echoed = _echoed_blocks(m) if echo_reasoning else None
    if echoed is not None:
        return echoed          # 上一轮的原生块：原样复活，勿由内核字段重建
    blocks: list[dict] = []
    if getattr(m, "content", ""):
        blocks.append({"type": "text", "text": m.content})
    for img in (getattr(m, "images", None) or []):
        block = await _image_block(img, fetch_image)
        if block:
            blocks.append(block)
    for tc in (getattr(m, "tool_calls", None) or []):
        blocks.append(_tool_use_block(tc))
    return blocks


def _echoed_blocks(m) -> Optional[list]:
    """上一轮留下的原生块凭据 → 原样回传的 content blocks；无凭据 / 不可解析返回 None。

    整条消息原样回传而非只塞思考块：官方要求"原样、保持原顺序，改一个字符即 400"；
    交错思考（interleaved thinking）下思考块还会夹在多个 tool_use 之间，顺序错同样 400。
    """
    raw = getattr(m, "reasoning_echo", None)
    if not raw or getattr(m, "role", "") != "assistant":
        return None
    try:
        blocks = json.loads(raw)
    except ValueError:
        return None
    return blocks if isinstance(blocks, list) and blocks else None


async def _image_block(img, fetch_image) -> Optional[dict]:
    """图片 → image block。原生协议只认 base64（不像 OpenAI 可直接给 URL）。"""
    if not img:
        return None
    if isinstance(img, dict):
        media = img.get("mime") or img.get("media_type") or "image/png"
        data = img.get("data") or ""
    else:
        media, data = await fetch_image(img)
    if not data:
        return None
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": data}}


def _tool_use_block(tc: dict) -> dict:
    """OpenAI 工具调用 → tool_use 块（arguments 是 JSON 字符串，需还原成对象）。"""
    fn = tc.get("function") or {}
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        args = {}
    return {"type": "tool_use", "id": tc.get("id") or "",
            "name": fn.get("name") or "", "input": args}


def native_tools(tools) -> Optional[list]:
    """OpenAI 工具声明 → 原生声明：`parameters` 改名 `input_schema`。"""
    normalized = Tool.normalize(tools)
    if not normalized:
        return None
    out = []
    for t in normalized:
        fn = t.get("function") or {}
        out.append({
            "name": fn.get("name") or "",
            "description": fn.get("description") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out or None


def native_tool_choice(choice, parallel: Optional[bool] = None) -> Optional[dict]:
    """OpenAI tool_choice → 原生。原生没有 `required`，对应 `any`（必须调某个工具）。

    原生没有独立的并行开关：并行与否由**工具选择项**承载（`disable_parallel_tool_use`），
    所以 `parallel=False` 时并进该字段；只表达"别并行"而没指定选择时补 `auto`。
    """
    out = _choice_of(choice)
    if out is None:
        if parallel is not False:
            return None
        out = {"type": "auto"}
    if parallel is False:
        out["disable_parallel_tool_use"] = True
    return out


def _choice_of(choice) -> Optional[dict]:
    """tool_choice 的形态转换（不含并行开关，便于单独取用与判定是否"强制"）。"""
    if choice is None:
        return None
    if isinstance(choice, str):
        base = _TOOL_CHOICE.get(choice)
        return dict(base) if base else None
    if isinstance(choice, dict):
        name = (choice.get("function") or {}).get("name") or choice.get("name")
        if name:
            return {"type": "tool", "name": name}
    return None


# ─────────────────────────── 响应方向：原生 → 内核 ───────────────────────────
def new_state() -> dict:
    """一次请求的累积器（usage / 工具槽位 / 思考签名 / 停止原因 / 原生块 / 记账）。

    `blocks` 按原生块索引登记重建出的块、`order` 记块序列 —— 二者合成回传凭据。
    `notes` 由调用方在组装载荷时填入（如"工具选择被降级"），收尾时并入 `stats.extra`。
    """
    return {"usage": {}, "tools": {}, "slots": {}, "seq": 0,
            "signature": "", "stop": "", "stop_seq": "", "model": "", "id": "",
            "blocks": {}, "order": [], "notes": {}}


def on_event(st: dict, obj: dict, name: str) -> list:
    """一个原生流式事件 → 内核事件列表（并更新累加器）。"""
    kind = obj.get("type")
    if kind == "error":
        raise RuntimeError(f"[{name}] 服务端错误：{error_text(json.dumps(obj).encode())}")
    if kind in ("message_start", "message_delta"):
        _on_message_event(st, obj)
        return []
    if kind == "content_block_start":
        return _on_block_start(st, obj)
    if kind == "content_block_delta":
        return _on_block_delta(st, obj)
    return []


def _on_message_event(st: dict, obj: dict) -> None:
    """message_start 给输入侧 usage，message_delta 给输出侧与停止原因。"""
    if obj.get("type") == "message_start":
        msg = obj.get("message") or {}
        st["usage"].update(msg.get("usage") or {})
        st["id"] = msg.get("id") or st["id"]
        st["model"] = msg.get("model") or st["model"]
        return
    st["usage"].update(obj.get("usage") or {})
    delta = obj.get("delta") or {}
    st["stop"] = delta.get("stop_reason") or st["stop"]
    st["stop_seq"] = delta.get("stop_sequence") or st["stop_seq"]


def _on_block_start(st: dict, obj: dict) -> list:
    """tool_use 块开始即有名字 → 立刻下发 tool_call_delta，供前端显示"正在调用 X"。"""
    blk = obj.get("content_block") or {}
    _record_block(st, obj.get("index", 0), blk, partial=True)
    if blk.get("type") != "tool_use":
        return []
    slot = st["seq"]
    st["seq"] += 1
    st["slots"][obj.get("index", 0)] = slot
    item = {"index": slot, "id": blk.get("id") or f"toolu_{slot}", "type": "function",
            "function": {"name": blk.get("name") or "", "arguments": ""}}
    st["tools"][slot] = item
    return [{"tool_call_delta": {"index": slot, "id": item["id"],
                                 "name": item["function"]["name"]}}]


def _record_block(st: dict, idx: int, blk: dict, partial: bool) -> dict:
    """登记一个原生块（回传凭据的唯一来源）。

    `partial=True` 为流式起始：tool_use 的参数还在分片路上，先用 `_json` 空串占位，
    待 `_on_block_delta` 拼接、收尾时再解析成对象。
    """
    kind = blk.get("type")
    if kind == "tool_use":
        item = {"type": "tool_use", "id": blk.get("id") or "",
                "name": blk.get("name") or ""}
        if partial:
            item["_json"] = ""
        else:
            item["input"] = blk.get("input") or {}
        st["blocks"][idx] = item
    else:
        st["blocks"][idx] = dict(blk)      # thinking / text / redacted_thinking：原样留存
    st["order"].append(idx)
    return st["blocks"][idx]


def _on_block_delta(st: dict, obj: dict) -> list:
    """块内增量：正文 / 思考 / 工具参数分片 / 思考签名。"""
    delta = obj.get("delta") or {}
    kind = delta.get("type")
    blk = st["blocks"].get(obj.get("index", 0))
    if kind == "text_delta":
        text = delta.get("text") or ""
        if blk is not None:
            blk["text"] = blk.get("text", "") + text
        return [{"content": text}] if text else []
    if kind == "thinking_delta":
        text = delta.get("thinking") or ""
        if blk is not None:
            blk["thinking"] = blk.get("thinking", "") + text
        return [{"reasoning": text}] if text else []
    if kind == "signature_delta":
        sig = delta.get("signature") or ""
        if blk is not None:
            blk["signature"] = blk.get("signature", "") + sig
        _append_signature(st, sig)
        return []
    if kind == "input_json_delta":
        if blk is not None:
            blk["_json"] = blk.get("_json", "") + (delta.get("partial_json") or "")
        slot = st["slots"].get(obj.get("index", 0))
        if slot is not None:
            st["tools"][slot]["function"]["arguments"] += delta.get("partial_json") or ""
    return []


def _append_signature(st: dict, sig: str) -> None:
    """思考块签名按顺序拼接留存 —— 多轮原样回传的凭据，丢了就回不去。"""
    if not sig:
        return
    st["signature"] += (sig if not st["signature"] else SIG_SEP + sig)


def content_events(blocks: list, st: dict) -> list:
    """非流式 content blocks → 内核事件（保持原有顺序：思考在正文之前）。"""
    events: list[dict] = []
    for i, blk in enumerate(blocks or []):
        kind = blk.get("type")
        _record_block(st, i, blk, partial=False)
        if kind == "text" and blk.get("text"):
            events.append({"content": blk["text"]})
        elif kind == "thinking":
            if blk.get("thinking"):
                events.append({"reasoning": blk["thinking"]})
            _append_signature(st, blk.get("signature") or "")
        elif kind == "tool_use":
            events.extend(_tool_events(blk, st))
    return events


def _tool_events(blk: dict, st: dict) -> list:
    slot = st["seq"]
    st["seq"] += 1
    args = blk.get("input")
    st["tools"][slot] = {
        "index": slot, "id": blk.get("id") or f"toolu_{slot}", "type": "function",
        "function": {"name": blk.get("name") or "",
                     "arguments": args if isinstance(args, str)
                     else json.dumps(args or {}, ensure_ascii=False)},
    }
    return [{"tool_call_delta": {"index": slot, "id": st["tools"][slot]["id"],
                                 "name": st["tools"][slot]["function"]["name"]}}]


def finish_events(st: dict, meter: Meter) -> list[dict]:
    """收尾帧：完整工具调用（若有）+ done（原始 usage + 归一 stats）。"""
    out: list[dict] = []
    if st["tools"]:
        out.append({"tool_calls": [st["tools"][k] for k in sorted(st["tools"])]})
    extra = _finish_extra(st)
    out.append({"done": True, "usage": st["usage"],
                "stats": meter.finish(usage_from(st["usage"], "anthropic"),
                                      map_stop_reason(st["stop"]),
                                      st["stop_seq"], extra)})
    return out


def _finish_extra(st: dict) -> Optional[dict]:
    """签名、回传凭据、响应 id 与组装期记账进 stats.extra（调用方落库/排查）。"""
    extra: dict[str, Any] = dict(st.get("notes") or {})
    if st["signature"]:
        extra["thinking_signature"] = st["signature"]
    blocks = _echo_blocks(st)
    if blocks:
        extra["native_blocks"] = json.dumps(blocks, ensure_ascii=False)
    if st["id"]:
        extra["response_id"] = st["id"]
    return extra or None


def _echo_blocks(st: dict) -> Optional[list]:
    """需要原样回传的原生块序列；无思考块时返回 None。

    只带思考块是刻意的：正文与 tool_calls 内核已能无损重建，整条回传只会让每轮响应
    的 stats 无谓膨胀。而思考块含签名（与思考文本逐字绑定）与加密数据，内核字段
    表达不了，只能在原生块序列里保真。
    """
    blocks = _finalize_blocks(st)
    if not any(b.get("type") in _ECHO_TYPES for b in blocks):
        return None
    return blocks


def _finalize_blocks(st: dict) -> list:
    """收尾原生块：拼好的参数 JSON 解析成对象；空文本块丢弃（原生协议拒收空文本块）。"""
    out: list[dict] = []
    for idx in st["order"]:
        blk = st["blocks"].get(idx)
        if blk is None:
            continue
        if "_json" in blk:
            raw = blk.pop("_json")
            try:
                blk["input"] = json.loads(raw) if raw else {}
            except ValueError:
                blk["input"] = {}
        if blk.get("type") == "text" and not blk.get("text"):
            continue
        out.append(blk)
    return out


def parse_sse(line: str) -> Optional[dict]:
    """解析一行 SSE。

    只认 `data:` 行 —— 事件类型一律从 JSON 的 `type` 字段取。`event:` 行与 JSON 必然
    同值，多读一处只会多一个漂移点。
    """
    if not line or not line.startswith("data:"):
        return None
    text = line[5:].strip()
    if not text or text == "[DONE]":
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def error_text(raw: bytes) -> str:
    """错误体优先取 error.message（比整段 JSON 可读得多）。"""
    text = (raw or b"").decode("utf-8", "ignore")
    try:
        obj = json.loads(text)
    except ValueError:
        return text[:500]
    err = obj.get("error") if isinstance(obj, dict) else None
    if isinstance(err, dict) and err.get("message"):
        return f"{err.get('type') or 'error'}: {err['message']}"
    return text[:500]


__all__ = [
    "to_native_messages", "native_tools", "native_tool_choice",
    "new_state", "on_event", "content_events", "finish_events",
    "parse_sse", "error_text", "SIG_SEP",
]
