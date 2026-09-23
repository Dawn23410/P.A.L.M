"""能力矩阵前置拦截：在发请求**之前**拦住必然失败或被静默忽略的输入。

为什么这件事该由内核做
----------------------
"支不支持视觉、能吃哪些文档类型、单个文件多大"是**供应商/模型级**事实
（数据源：`docs/各供应商各模型支持能力_v2.0.md`），而调用方手上通常只有一个
模型名，根本无从判断。等请求发出去再让服务端报 400，既白跑一次往返，
拿回来的错误也常是模糊的 "invalid request" —— 内核手上正好有 `Profile` /
`ModelRule`，在这里拦掉信息最准、代价最低。

三条铁律
--------
1. **只拦"已知不支持"**。能力矩阵是抓来的，有覆盖盲区：`generic` 档位连模型名
   都不固定（本机 ollama 拉什么是什么），硬拦会把 `llava` 这类合法用法直接打死。
   因此凡档位标了 `capabilities_known=False`，一律**放行**并返回一条
   `capability_unknown` 记账 —— 宁可放过，不可错杀；需要严格预检的调用方
   请改用 `capabilities_for()` 自行决策。
2. **只看 `Message`，不看 payload**。payload 是各家组装后的产物，形态已经漂移；
   入参面是统一的，校验必须挂在这一层才不会随协议实现变化而漏检。
3. **报错要能照着改**。消息里必须写清：第几条消息、什么类型、超了多少、
   支持什么、该换什么。只说 "unsupported" 等于没说。
"""
from __future__ import annotations

from typing import Any, Optional

from ..errors import CapabilityError
from ..models import Message
from ._profiles import ModelRule, Profile, resolve

# `CapabilityError` 现定义于内核统一异常层（palm_llm/errors.py），此处仅重导出，
# 保持既有 `from palm_llm.providers._capability import CapabilityError` 导入路径不变。


def capabilities_for(base_url: str = "", type_hint: str = "",
                     model: str = "") -> dict:
    """查询「端点 + 模型」的能力矩阵（供调用方预检、或做 UI 的能力提示）。

    `capabilities_known=False` 表示该档位未收录矩阵 —— 此时各字段是保守默认值，
    **不代表模型真的不支持**，调用方应自行决定是否放行。
    """
    profile, rule = resolve(base_url, model, type_hint)
    return {
        "profile": profile.name,
        "capabilities_known": profile.capabilities_known,
        "supports_vision": profile.supports_vision,
        "doc_mimes": tuple(profile.doc_mimes),
        "max_file_mb": profile.max_file_mb,
        "max_output": profile.max_output,
        "needs_reasoning_echo": profile.needs_reasoning_echo,
        "reject_documents": profile.reject_documents,
        "rule": getattr(rule, "pattern", None),
    }


def check_capabilities(messages: list[Message], profile: Profile,
                       model: str = "", provider: str = "",
                       rule: Optional[ModelRule] = None) -> dict:
    """按能力矩阵校验入参；违规抛 `CapabilityError`。

    返回值是一组**非致命**记账（无警告时为空 dict），调用方应并入 `stats.extra`：
    内核只对"已知不支持"硬拦，其余情况如实披露，不替调用方做决定。

    `profile` 必须是**已二级合并**后的（`resolve` 的返回值），否则模型级覆盖
    （如 GLM-5.3-Flash 单独放开文件）不会生效。
    """
    images = _by_field(messages, "images")
    files = _by_field(messages, "files")
    if not images and not files:
        return {}

    if not profile.capabilities_known:
        kinds = "+".join(k for k, v in (("图片", images), ("文档", files)) if v)
        return {"capability_unknown": (
            f"档位 {profile.name!r} 未收录模型能力矩阵（模型 {model or '未指定'}），"
            f"本次 {kinds} 输入未做能力校验")}

    where = _RuleHint(rule)
    notes: dict = {}
    _check_vision(profile, model, provider, images, where)
    _check_documents(profile, model, provider, files, notes, where)
    return notes


# ─────────────────────────── 校验项 ───────────────────────────
def _check_vision(profile: Profile, model: str, provider: str,
                  images: list[tuple[int, Any]], where: "_RuleHint") -> None:
    if not images or profile.supports_vision:
        return
    raise CapabilityError(
        f"[{provider or 'palm_llm'}] 模型 {model or '（未指定）'} 不支持视觉输入："
        f"{_where([i for i, _ in images])}共带 {len(images)} 张图"
        f"（能力档 {profile.name}）{where}。"
        f"处理：改用支持视觉的模型，或移除这些消息的 images。")


def _check_documents(profile: Profile, model: str, provider: str,
                     files: list[tuple[int, Any]], notes: dict,
                     where: "_RuleHint") -> None:
    if not files:
        return
    # 先按类型分流：`files` 里混进图片是常态（调用方不区分两个字段），
    # 图片型附件归视觉闸门，其余归文档闸门 —— 否则会给图片报"不支持文档"的错。
    image_files = [(i, it) for i, it in files if _mime_of(it).startswith("image/")]
    doc_files = [(i, it) for i, it in files if not _mime_of(it).startswith("image/")]
    if image_files:
        _check_vision(profile, model, provider, image_files, where)
    if not doc_files:
        return

    if profile.reject_documents:
        raise CapabilityError(
            f"[{provider or 'palm_llm'}] 模型 {model or '（未指定）'} 不原生支持文档输入："
            f"{_where([i for i, _ in doc_files])}共带 {len(doc_files)} 个文件"
            f"（能力档 {profile.name}）{where}。"
            f"处理：先用该厂商独立的文件解析/上传通道转成纯文本或 file_id，"
            f"再把结果作为 content 传入。")

    limit = (profile.max_file_mb or 0) * 1024 * 1024
    declared = tuple(profile.doc_mimes or ())
    total = 0
    total_known = True
    for idx, item in doc_files:
        mime = _mime_of(item)
        if not mime:
            total_known = False
            notes.setdefault("capability_size_unchecked",
                             "存在无法判定类型的附件（远程 URL 未带 mime），"
                             "已跳过类型与大小校验")
            continue
        if declared and not _mime_allowed(mime, declared):
            raise CapabilityError(
                f"[{provider or 'palm_llm'}] 模型 {model or '（未指定）'} 不支持 {mime} 文档："
                f"{_where([idx])}（能力档 {profile.name}）{where}。"
                f"支持的类型：{', '.join(declared)}。"
                f"处理：先转成支持的类型（如 {declared[0]}），或换模型。")
        size = _size_of(item)
        if size is None:
            total_known = False
            continue
        if limit and size > limit:
            raise CapabilityError(
                f"[{provider or 'palm_llm'}] {_where([idx])}的文档"
                f"（{mime}，约 {_mb(size)} MB）超过单文件上限 {profile.max_file_mb} MB"
                f"（模型 {model or '未指定'}）{where}。处理：压缩或拆分文件。")
        total += size

    if limit and total_known and total > limit:
        raise CapabilityError(
            f"[{provider or 'palm_llm'}] 本次文档合计约 {_mb(total)} MB，"
            f"超过单请求上限 {profile.max_file_mb} MB（模型 {model or '未指定'}）{where}。"
            f"处理：减少文件数量或压缩后再传。")


# ─────────────────────────── 取值工具 ───────────────────────────
def _by_field(messages, field: str) -> list[tuple[int, Any]]:
    """收集每条消息上某字段的附件（返回 (消息下标, 附件)），下标从 1 起便于人读。"""
    out: list[tuple[int, Any]] = []
    for i, m in enumerate(messages or [], 1):
        for item in (getattr(m, field, None) or []):
            out.append((i, item))
    return out


def _mime_of(item: Any) -> str:
    """附件的 MIME（小写、去参数）。拿不到就返回空串 —— 不做额外网络探测。"""
    if isinstance(item, dict):
        mime = str(item.get("mime") or "")
        if mime:
            return _clean_mime(mime)
        return _mime_from_uri(item.get("data") or item.get("url") or "")
    if isinstance(item, str):
        return _mime_from_uri(item)
    return ""


def _mime_from_uri(uri: Any) -> str:
    if isinstance(uri, str) and uri.startswith("data:"):
        return _clean_mime(uri.partition(",")[0][5:])
    return ""            # http(s) URL / 本地路径：类型未知，不猜


def _clean_mime(raw: str) -> str:
    return (raw or "").split(";")[0].strip().lower()


def _size_of(item: Any) -> Optional[int]:
    """附件的原始字节数；拿不到返回 None（远程 URL 不额外发 HEAD 请求）。

    base64 按文本长度反推（不真解码）：`len*3/4`，已扣除填充符。是**近似值**，
    用于大小闸门足够（误差远小于"超没超 50 MB"这一量级）。
    """
    if isinstance(item, dict):
        explicit = item.get("size")
        if isinstance(explicit, (int, float)) and explicit > 0:
            return int(explicit)
        data = item.get("data")
        return _b64_len(data) if isinstance(data, str) and data.startswith("data:") else None
    if isinstance(item, str) and item.startswith("data:"):
        return _b64_len(item)
    return None


def _b64_len(uri: str) -> int:
    payload = uri.partition(",")[2]
    return len(payload.rstrip("=")) * 3 // 4


def _mime_allowed(mime: str, declared: tuple) -> bool:
    """声明项支持精确匹配，也支持 `image/*` 这类前缀通配。"""
    for entry in declared:
        want = _clean_mime(str(entry))
        if not want:
            continue
        if want.endswith("/*") and mime.startswith(want[:-1]):
            return True
        if want == mime:
            return True
    return False


def _where(indexes: list[int]) -> str:
    uniq = sorted(set(indexes))
    return f"第 {'、'.join(str(i) for i in uniq)} 条消息"


def _mb(size: int) -> str:
    return f"{size / 1024 / 1024:.2f}"


class _RuleHint:
    """把命中的规则名缀在报错末尾 —— 规则数据出问题时要能一眼定位到那一条。"""

    __slots__ = ("pattern",)

    def __init__(self, rule: Optional[ModelRule]):
        self.pattern = getattr(rule, "pattern", None)

    def __str__(self) -> str:
        return f"，命中规则 {self.pattern!r}" if self.pattern else ""


__all__ = ["CapabilityError", "capabilities_for", "check_capabilities"]
