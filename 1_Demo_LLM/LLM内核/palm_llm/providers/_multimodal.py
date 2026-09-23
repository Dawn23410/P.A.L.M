"""多模态 content blocks 构造（纯逻辑，无 IO）。

把「文本 + 图像 + 文档」转成各协议的 content blocks：

- `openai`（默认）：图像 `image_url` + 内联 data URI；文档 `file` + `file_data`
- `anthropic`：原生 `image` / `source`、`document` / `source`（base64 + media_type）

图像/文档入参兼容两种形态（两者一致，避免调用方记两套）：

- `str`：data URI（`data:image/png;base64,...`）或 http(s) URL
- `dict`：`{"data": <base64 或 data URI>, "mime": "application/pdf", "name": "a.pdf"}`

来源：本模块的 Anthropic 分支与 dict 形态由 P.A.L.M 主工程的
`palm/adapters/model/provider.py` 迁入，主工程现改为复用本模块（单一实现）。

协议差异（依据官方文档，2026-09-23 核对）
----------------------------------------
- OpenAI **Chat Completions** 的文件块只认 `.pdf`（`file_data` 必须是
  `data:application/pdf;base64,...`）；其他类型要走 Responses API 的 `input_file`。
  故 openai 分支不做类型白名单以外的特殊处理，越界类型由 `capability.py` 在发请求前拦掉。
- Anthropic 的文档块是 `{"type":"document","source":{"type":"base64",...}}`（PDF），
  与图像块的 `{"type":"image",...}` 同构。
"""
from __future__ import annotations

from typing import Any, Optional

DEFAULT_MIME = "image/png"
DEFAULT_FILE_MIME = "application/octet-stream"

# 扩展名兜底：dict 形态没给 name 时，按 mime 反推一个像样的文件名
_EXT_BY_MIME = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/csv": "csv",
    "application/json": "json",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def data_uri(media: Any, default_mime: str = DEFAULT_MIME) -> str:
    """把任意形态的「图像/文档」入参归一为 data URI（OpenAI 的 image_url/file_data 只吃这个）。

    `str` 原样返回（已是 URL 或 data URI）；`dict` 取 `data` + `mime`，已是 data URI 就透传，
    否则按 `default_mime` 拼 `data:<mime>;base64,<data>`；其余类型退化为 `str()`。

    图像与文档**只差默认 mime**（`DEFAULT_MIME` / `DEFAULT_FILE_MIME`），故合成一个函数、
    由调用方传 `default_mime`；原先的 `image_url` / `file_uri` 是它的两个薄包装，已合并掉。
    """
    if isinstance(media, str):
        return media
    if isinstance(media, dict):
        data = media.get("data") or ""
        mime = media.get("mime") or default_mime
        if data.startswith("data:"):
            return data
        return f"data:{mime};base64,{data}"
    return str(media)


def split_data_uri(uri: str) -> tuple[str, str]:
    """拆 data URI → (mime, base64)；非 data URI 原样作为 data 返回。"""
    if uri.startswith("data:"):
        head, _, payload = uri.partition(",")
        mime = head[5:].split(";")[0] or DEFAULT_MIME
        return mime, payload
    return DEFAULT_MIME, uri


def file_name(doc: Any) -> str:
    """文档显示名：调用方给了就用；否则按 mime 反推一个（网关/模型侧靠它判断类型）。"""
    if isinstance(doc, dict) and doc.get("name"):
        return str(doc["name"])
    mime, _ = split_data_uri(data_uri(doc, DEFAULT_FILE_MIME))
    return f"document.{_EXT_BY_MIME.get(mime, 'bin')}"


def content_blocks(text: str, images: Any, mode: str = "openai",
                   files: Optional[list] = None) -> list[dict]:
    """纯文本 + 图像 + 文档 → 多模态 content blocks（供视觉/文档模型分析）。

    `mode="anthropic"` 走 Anthropic 原生 image/document/source；其余走 OpenAI 兼容。
    """
    blocks: list[dict] = [{"type": "text", "text": text or ""}]
    for img in images or []:
        uri = data_uri(img)                      # 图像：默认 mime = image/*
        if mode == "anthropic":
            mime, data = split_data_uri(uri)
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": data},
            })
        else:
            blocks.append({"type": "image_url", "image_url": {"url": uri}})
    for doc in files or []:
        uri = data_uri(doc, DEFAULT_FILE_MIME)   # 文档：默认 mime = octet-stream
        mime, data = split_data_uri(uri)
        if mode == "anthropic":
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": mime, "data": data},
            })
        else:
            blocks.append({
                "type": "file",
                "file": {"filename": file_name(doc), "file_data": uri},
            })
    return blocks
