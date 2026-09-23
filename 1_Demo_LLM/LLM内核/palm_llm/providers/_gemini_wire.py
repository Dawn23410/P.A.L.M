"""Gemini GenerateContent 原生线格式 ↔ 内核格式的双向转换。

为什么单独成文件：这一层是**结构级**翻译，与 provider 的传输职责（端点、鉴权、重试、
思考配置）是两件事。混在一起会突破 500 行上限，也让"传输出错"和"翻译出错"难以区分。

阵营 C 的结构级差异（没有一个是字段名层面的，靠映射表翻不出来）
--------------------------------------------------------------
1. **角色只有 `user` / `model`** —— 没有 `assistant`、**也没有 `system` 角色**
   （system 必须外提为顶层 `systemInstruction`）。
2. **内容一律 `contents[].parts[]`** —— 文本 / 图片 / 工具调用混在同一个 parts 数组里，
   不像 OpenAI 那样按 `content` 与 `tool_calls` 两个字段分开放。
3. **工具声明是 `tools[].functionDeclarations[]`**（JSON Schema 近似 OpenAPI 3.0）。
4. **工具结果用 `functionResponse` part**，不是 `role="tool"` 消息
   （官方：`functionResponse` 带 `id` + `name`）。
5. **流式 SSE 没有 `[DONE]`** —— 靠 HTTP 连接关闭结束。
6. **鉴权是 `x-goog-api-key`**，不是 `Authorization: Bearer`。
7. **思考块是 `thought` 标志 + `thoughtSignature`**，官方口径是"把整条响应连同全部
   parts 原样回传"，与 Anthropic 的思考块回传同源但字段结构不同。

思考块回传（双向）
------------------
响应方向把候选的 `content.parts` 整体序列化进 `stats.extra.native_blocks`（不透明字符串），
请求方向若上一轮留下了该凭据就整条原样复活。只在本轮**带 tools** 时回传 —— 官方把
"函数调用的签名"列为必需项，其余场景只是"建议"，而回传历史 parts 会持续计入输入 token。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..models import Tool
from ._multimodal import split_data_uri
from ._telemetry import Meter, usage_from

# 真·原生 id 的特征：我们自己补的 id 用 `fc_<n>`，回传前要剥掉
# （模型没给 id 时凭空塞一个，服务端会认不出来 —— 与 tooltext 的 call_txt_ 同一约定）
_SYNTHETIC_ID = re.compile(r"^fc_\d+$")

# finishReason → OpenAI 口径
_FINISH = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
    "LANGUAGE": "stop",
    "OTHER": "stop",
    # 模型把函数调用写坏了：不是正常结束，交给调用方处理
    "MALFORMED_FUNCTION_CALL": "error",
    "UNEXPECTED_TOOL_CALL": "error",
}


# ─────────────────────────── 请求方向：内核 → 原生 ───────────────────────────
async def to_contents(messages, fetch_image, echo_reasoning: bool = False
                      ) -> tuple[str, list[dict]]:
    """(system 文本, 原生 contents)。

    `echo_reasoning` 只在**本次请求带 tools** 时为真（官方：函数调用的签名必需回传）。
    """
    system_parts: list[str] = []
    out: list[dict] = []
    for m in messages:
        role = getattr(m, "role", "user")
        if role == "system":
            if getattr(m, "content", ""):
                system_parts.append(m.content)
            continue
        parts = await _parts_for(m, fetch_image, echo_reasoning)
        if parts:
            _append_content(out, _role(role), parts)
    return "\n\n".join(system_parts), out


def _role(role: str) -> str:
    """内核角色 → 原生角色（只有 user / model）。"""
    return "model" if role == "assistant" else "user"


def _append_content(out: list, role: str, parts: list) -> None:
    """连续同角色合并成一条 —— 原生只有 user/model 两值，同角色连排会被视作一条内容。"""
    if out and out[-1]["role"] == role:
        out[-1]["parts"].extend(parts)
    else:
        out.append({"role": role, "parts": parts})


async def _parts_for(m, fetch_image, echo_reasoning: bool) -> list:
    """单条内核 Message → 原生 parts。"""
    role = getattr(m, "role", "user")
    if role == "tool":
        return [_function_response(m)]
    echoed = _echoed_parts(m) if echo_reasoning else None
    if echoed is not None:
        return echoed            # 上一轮的原生 parts：原样复活，勿由内核字段重建
    parts: list[dict] = []
    if getattr(m, "content", ""):
        parts.append({"text": m.content})
    for img in (getattr(m, "images", None) or []):
        part = await _inline_data(img, fetch_image)
        if part:
            parts.append(part)
    # 文档附件走同一个 inlineData（原生 PDF 就按 inline 计费与计数，官方口径）
    for doc in (getattr(m, "files", None) or []):
        part = await _inline_data(doc, fetch_image, default_mime="application/pdf")
        if part:
            parts.append(part)
    for tc in (getattr(m, "tool_calls", None) or []):
        part = _function_call_part(tc)
        if part:
            parts.append(part)
    return parts


def _function_response(m) -> dict:
    """工具结果 → functionResponse part。

    `id` 只在**是模型给的真 id** 时回传：我们自己补的 `fc_<n>` 服务端认不出来，
    塞过去只会换来一个 invalid argument。`name` 必填（官方口径）。
    """
    call_id = getattr(m, "tool_call_id", "") or ""
    inner: dict[str, Any] = {"result": getattr(m, "content", "") or ""}
    if getattr(m, "tool_error", False):
        inner["error"] = True          # 官方建议工具失败时标明，否则模型分不清成败
    body: dict[str, Any] = {"name": getattr(m, "name", "") or "", "response": inner}
    if call_id and not _SYNTHETIC_ID.match(call_id):
        body["id"] = call_id
    return {"functionResponse": body}


async def _inline_data(img, fetch_image, default_mime: str = "image/png") -> Optional[dict]:
    """图像/文档 → inlineData part。

    原生只认内联 base64（远程 URL 需先上传成 fileData）；PDF 与图片同构，
    都是 `{"inlineData": {"mimeType","data"}}`，故共用本函数。
    """
    if not img:
        return None
    if isinstance(img, dict):
        mime = img.get("mime") or img.get("mimeType") or img.get("media_type") or ""
        data = img.get("data") or ""
        if data.startswith("data:"):
            mime, data = split_data_uri(data)
    else:
        mime, data = await fetch_image(img)
    if not data:
        return None
    return {"inlineData": {"mimeType": mime or default_mime, "data": data}}


def _function_call_part(tc: dict) -> Optional[dict]:
    """内核工具调用 → functionCall part（`args` 必须是**对象**，不是 JSON 字符串）。

    与 `functionResponse` 同一约定：只有模型给过的真 id 才回传，我们自己补的 `fc_<n>`
    丢掉 —— 否则多轮里 pair 不上，服务端会报 invalid argument。
    """
    fn = tc.get("function") or {}
    name = fn.get("name") or ""
    if not name:
        return None
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            args = {}
    body: dict[str, Any] = {"name": name, "args": args or {}}
    call_id = tc.get("id") or ""
    if call_id and not _SYNTHETIC_ID.match(call_id):
        body["id"] = call_id
    return {"functionCall": body}


def function_declarations(tools) -> Optional[list]:
    """OpenAI 工具声明 → 原生 tools 数组；参数 Schema 近似 OpenAPI 3.0，直接搬。"""
    normalized = Tool.normalize(tools)
    if not normalized:
        return None
    out = []
    for t in normalized:
        fn = t.get("function") or {}
        out.append({
            "name": fn.get("name") or "",
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": out}]


def tool_config(choice, parallel: Optional[bool] = None) -> Optional[dict]:
    """OpenAI tool_choice → 原生 toolConfig.functionCallingConfig。

    模式三值：`AUTO`（默认）/ `ANY`（必须调某个）/ `NONE`（禁止）。
    ⚠️ 具名强制用 `allowedFunctionNames` 表达，模式仍是 `ANY`。
    `parallel` 在原生里没有对应开关（>1 个调用由模型自行决定），故**不下发**、
    也不假装支持 —— 传了 `parallel=False` 只记一条 note，由 provider 层记账。
    """
    if choice is None:
        return None
    if isinstance(choice, str):
        mode = {"auto": "AUTO", "none": "NONE", "required": "ANY"}.get(choice)
        return {"functionCallingConfig": {"mode": mode}} if mode else None
    if isinstance(choice, dict):
        name = (choice.get("function") or {}).get("name") or choice.get("name")
        if name:
            return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}}
    return None


# ─────────────────────────── 响应方向：原生 → 内核 ───────────────────────────
def new_state() -> dict:
    """一次请求的累积器（工具槽位 / 原生 parts / 停止原因 / usage / 记账）。"""
    return {"tools": {}, "seq": 0, "parts": [], "finish": "", "block": "",
            "usage": {}, "model": "", "id": "", "notes": {}}


def events_from(chunk: dict, st: dict, name: str) -> list[dict]:
    """一个原生响应块（流式的一帧或非流式整包）→ 内核事件列表。"""
    _absorb_meta(chunk, st)
    events: list[dict] = []
    for cand in (chunk.get("candidates") or []):
        parts = ((cand.get("content") or {}).get("parts")) or []
        for part in parts:
            events.extend(_part_events(part, st))
        if cand.get("finishReason"):
            st["finish"] = cand["finishReason"]
    return events


def _absorb_meta(chunk: dict, st: dict) -> None:
    """收拢元信息：usage / 模型名 / 响应 id / 被安全策略拦下的原因。"""
    if chunk.get("usageMetadata"):
        st["usage"].update(chunk["usageMetadata"])
    if chunk.get("modelVersion"):
        st["model"] = chunk["modelVersion"]
    if chunk.get("responseId"):
        st["id"] = chunk["responseId"]
    feedback = chunk.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        st["block"] = feedback["blockReason"]


def _part_events(part: dict, st: dict) -> list[dict]:
    """一个 part → 内核事件（并登记原生 parts 供回传）。"""
    if not isinstance(part, dict):
        return []
    st["parts"].append(part)
    if part.get("thought") and part.get("text"):
        return [{"reasoning": part["text"]}]          # 思考摘要
    if part.get("text"):
        return [{"content": part["text"]}]
    call = part.get("functionCall")
    if isinstance(call, dict):
        return _tool_events(call, st)
    return []                                          # thoughtSignature-only 等


def _tool_events(call: dict, st: dict) -> list[dict]:
    """原生一次给完整 functionCall（不像 OpenAI 分片），直接 delta + 整包。"""
    slot = st["seq"]
    st["seq"] += 1
    st["tools"][slot] = {
        "index": slot,
        "id": call.get("id") or f"fc_{slot}",
        "type": "function",
        "function": {"name": call.get("name") or "",
                     "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)},
    }
    item = st["tools"][slot]
    return [{"tool_call_delta": {"index": slot, "id": item["id"],
                                 "name": item["function"]["name"]}}]


def finish_events(st: dict, meter: Meter) -> list[dict]:
    """收尾帧：完整工具调用（若有）+ done（原始 usage + 归一 stats）。"""
    out: list[dict] = []
    if st["tools"]:
        out.append({"tool_calls": [st["tools"][k] for k in sorted(st["tools"])]})
    raw = st["block"] and "SAFETY" or st["finish"]
    reason = finish_reason(raw, bool(st["tools"]))
    extra = _finish_extra(st, raw)
    out.append({"done": True, "usage": st["usage"],
                "stats": meter.finish(usage_from(st["usage"], "gemini"), reason, "", extra)})
    return out


def finish_reason(raw: str, has_calls: bool) -> str:
    """原生 finishReason → OpenAI 口径。

    有函数调用时统一报 `tool_calls`（与 OpenAI / Anthropic 一致）—— 否则按
    `finish_reason` 分支的调用方根本不会去执行工具。
    """
    if has_calls and raw in ("STOP", ""):
        return "tool_calls"
    return _FINISH.get(raw, "stop" if not raw else raw.lower())


def _finish_extra(st: dict, raw: str) -> Optional[dict]:
    """原生 parts、响应 id 与组装期记账进 stats.extra（调用方落库/排查）。"""
    extra: dict[str, Any] = dict(st.get("notes") or {})
    if raw:
        extra["finish_reason_vendor"] = raw
    if st["block"]:
        extra["block_reason"] = st["block"]
    bounds = _echo_credential(st)
    if bounds:
        extra["native_blocks"] = bounds
    if st["id"]:
        extra["response_id"] = st["id"]
    return extra or None


def _echo_credential(st: dict) -> Optional[str]:
    """需要原样回传的原生 parts 序列；不含任何签名时返回 None。

    只带"含签名或思考标志"的 parts 是刻意的：纯文本/纯 functionCall 内核已能无损重建，
    整条回传只会让每轮 stats 无谓膨胀。官方要求的是"签名原样"，签名一定附着在这些 part 上。
    """
    keep = [p for p in st["parts"] if _carries_signature(p)]
    return json.dumps(keep, ensure_ascii=False) if keep else None


def _carries_signature(part: dict) -> bool:
    return bool(part.get("thoughtSignature")) or bool(part.get("thought"))


def _echoed_parts(m) -> Optional[list]:
    """上一轮留下的原生 parts 凭据 → 原样复活的 parts；无凭据 / 不可解析返回 None。"""
    raw = getattr(m, "reasoning_echo", None)
    if not raw or getattr(m, "role", "") != "assistant":
        return None
    try:
        parts = json.loads(raw)
    except ValueError:
        return None
    return parts if isinstance(parts, list) and parts else None


def parse_sse(line: str) -> Optional[dict]:
    """解析一行 SSE。**没有 `[DONE]`** —— 原生靠连接关闭结束，故无需哨兵处理。"""
    if not line or not line.startswith("data:"):
        return None
    text = line[5:].strip()
    if not text:
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
    if isinstance(err, dict):
        status = err.get("status") or err.get("code") or ""
        message = err.get("message") or ""
        return f"{status}: {message}".strip(": ") or text[:500]
    return text[:500]


__all__ = [
    "to_contents", "function_declarations", "tool_config", "new_state",
    "events_from", "finish_events", "finish_reason", "parse_sse", "error_text",
]
