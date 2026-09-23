"""正文文本里的工具调用解析（无原生 tool_calls 时的降级通道）。

为什么需要
----------
不是所有端点都实现了原生 function calling：ollama 只对它"认得的模型模板"解析，
自定义 GGUF 一律把调用原样吐进正文；第三方网关也常有只回文本的。而模型写进正文的
调用形态是各家公开约定，逐家不同：

| 家族 | 正文形态 | 依据 |
|---|---|---|
| Hermes / Qwen2 / Qwen3 | `<tool_call>{"name":…,"arguments":{…}}</tool_call>` | Qwen 官方 function_call 文档 |
| Llama 3.1+ | `<|python_tag|>{"name":…,"parameters":{…}}<|eom_id|>` | vLLM `llama3_json` 解析器 |
| Mistral | `[TOOL_CALLS][{"name":…,"arguments":{…}}]` | vLLM `mistral` 解析器源码 |
| Qwen2.5（旧模板） | `✿FUNCTION✿: name` + `✿ARGS✿: {…}` | Qwen v2.5 官方文档 |
| 社区 GGUF | ` ```json {"name":…,"parameters":{…}} ``` ` | 无官方文档，故校验最严 |

三条安全阀（**同时**满足才认，否则原文原样放行）
----------------------------------------------
1. 本次请求**声明了** tools —— 没声明工具时模型不可能"在调用"；
2. 解析出的 `name` ∈ 已声明工具名；
3. 区域内的文本必须能解析成 JSON。
第 2 条不是形式主义：本项目自己就会输出讲解 `<tool_call>` 的文档与示例，只看标签形态
会把示例吃成一次真实调用。

为什么是流式安全的
------------------
正文逐帧到来，不能等收完再判断（那等于放弃流式）。做法是把"标记可能还没收全"的那一小段
**扣住不发**：扫描时空留 `最长标记长度 - 1` 个字符，进入标记后再缓冲到结束标记。
被扣住的内容只有两种归宿 —— 校验通过成为 tool_calls，否则原样放行。因此
"放行的正文 + 抽出的调用"始终等于模型的原始输出：**正文流不丢字、不重复、顺序不变**。
（`[TOOL_CALLS]` 没有结束标记，区域右边界取最后一个成功解析的 JSON 值，
其后的话作为尾巴原样放行 —— 见 `parse_region`。它相对 tool_calls 事件可能"先到"，
但那是两个不同通道，正文流内部的顺序不受影响。）

刻意不支持的形态
----------------
GLM-4-0414 开源模板的调用是「函数名换行 + JSON 参数」，**没有稳定标签**（官方示例自带
正则 `([^\n`]?)\n({.?})` 去抠）。这类"裸名字 + 裸 JSON"的规则会大面积误伤正常正文
（比如正文里出现一个 JSON 代码块），故不纳入。GLM 的 API 走原生 tools，不受影响。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ._telemetry import mark_finish_tool_calls

# (开始标记, 结束标记)；结束标记为 None 表示"其后全部属于该区域"（如 [TOOL_CALLS]）
MARKERS: tuple[tuple[str, Optional[str]], ...] = (
    ("<tool_call>", "</tool_call>"),
    ("<|python_tag|>", "<|eom_id|>"),
    ("[TOOL_CALLS]", None),
    ("✿FUNCTION✿", "✿RETURN✿"),
    ("```json", "```"),
)

# 扣住不发的最长"半个标记"：少于标记长度时无法判断是否为标记，只能等下一帧
_HOLD = max(len(start) for start, _ in MARKERS) - 1
# 单个区域的缓冲上限：模型没写结束标记时，超限就放弃解析（当普通正文放行）
_REGION_CAP = 65536

# 注意：`✿FUNCTION✿` 已被扫描层当作区域开始标记剥掉，故这里对**剩下的 body** 匹配，
# 不能再去搜那个标记本身（旧写法即在 body 里找 `✿FUNCTION✿`，永远匹配不到）。
_FN_RE = re.compile(r":?\s*([A-Za-z0-9_.\-]+)")
_ARGS_RE = re.compile(r"✿ARGS✿\s*:?\s*(\{.*)", re.DOTALL)


def declared_names(tools) -> set[str]:
    """从工具声明里取名字集合（兼容三种原生形状）。

    三家的声明形状不同，缺一种就会让安全阀 1 误判"本次没声明工具"、整套机制静默关闭：
      - OpenAI / ollama：`{"type":"function","function":{"name":…}}`
      - Anthropic：顶层 `{"name":…,"input_schema":…}`
      - Gemini：`{"functionDeclarations":[{"name":…},…]}`
    """
    out: set[str] = set()
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        decls = t.get("functionDeclarations")
        if isinstance(decls, list):
            out.update(d["name"] for d in decls
                       if isinstance(d, dict) and d.get("name"))
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        name = fn.get("name")
        if name:
            out.add(name)
    return out


class TextToolFilter:
    """流式扫描过滤器：把正文里的工具调用区域扣下，其余照常放行。

    `feed()` 投入正文、取回可放行的内容事件；`finish()` 收尾；`take_calls()` 取调用。
    """

    def __init__(self, names):
        self._names = set(names or ())
        self._on = bool(self._names)     # 没声明任何工具 → 整个机制关闭（安全阀 1）
        self._native = False             # 已走过原生 tool_calls → 不再产出文本解析结果
        self._buf = ""
        self._body = ""
        self._open: Optional[tuple] = None
        self._calls: list[dict] = []

    # ─────────────────────────── 对外 ───────────────────────────
    def feed(self, text: str) -> list[dict]:
        """投入一段正文，返回此刻可放行的内容事件。"""
        if not self._on:
            return [{"content": text}] if text else []
        self._buf += text
        out: list[dict] = []
        while self._step(out):
            pass
        return out

    def finish(self) -> list[dict]:
        """流结束：未闭合的区域按"到流末"善后，剩余缓冲放行。"""
        if not self._on:
            return []
        out: list[dict] = []
        if self._open is not None:
            self._body += self._buf
            self._buf = ""
            self._close(out, closed=False)
        self._flush(out)
        return out

    def release(self) -> list[dict]:
        """放弃解析、把一切缓冲原样放行（已经走原生 tool_calls 时用）。"""
        self._native = True
        if not self._on:
            return []
        out: list[dict] = []
        self._flush(out)
        return out

    def take_calls(self) -> list[dict]:
        return [] if self._native else self._calls

    # ─────────────────────────── 扫描 ───────────────────────────
    def _step(self, out: list) -> bool:
        """推进一次；返回是否还能继续推进。"""
        if self._open is not None:
            return self._in_region(out)
        return self._scan(out)

    def _scan(self, out: list) -> bool:
        """在标记之外：把最早标记之前的内容放行，或转入区域。"""
        pos, marker = self._find()
        if marker is None:
            self._release_tail(out)
            return False
        if pos:
            out.append({"content": self._buf[:pos]})
        self._buf = self._buf[pos + len(marker[0]):]
        self._open, self._body = marker, ""
        return True

    def _find(self):
        """缓冲里最早的**完整**开始标记 → (位置, 标记对)；没有则 (0, None)。

        只看完整标记：不完整的那几个字符由 `_release_tail` 扣住，下一帧自然会补齐。
        """
        best, hit = -1, None
        for marker in MARKERS:
            i = self._buf.find(marker[0])
            if i >= 0 and (best < 0 or i < best):
                best, hit = i, marker
        return (best, hit) if hit is not None else (0, None)

    def _release_tail(self, out: list) -> None:
        """放行除"可能是半个标记"的尾巴之外的全部内容。"""
        cut = len(self._buf) - _HOLD
        if cut > 0:
            out.append({"content": self._buf[:cut]})
            self._buf = self._buf[cut:]

    def _in_region(self, out: list) -> bool:
        """在区域内：等结束标记；无结束标记的则整段吃到流末。"""
        end = self._open[1]
        if end is None:
            self._body += self._buf
            self._buf = ""
            if len(self._body) > _REGION_CAP:
                self._flush(out)         # 过长：放弃解析，标记+正文原样照发
                return True              # 区域已关闭，后续按普通正文处理
            return False
        i = self._buf.find(end)
        if i >= 0:
            self._body += self._buf[:i]
            self._buf = self._buf[i + len(end):]
            self._close(out)
            return True
        if len(self._body) + len(self._buf) > _REGION_CAP:
            self._flush(out)             # 过长：放弃解析，原文照发
            return True
        # 结束标记可能还没收全 —— 只能挪走"确定不含其前缀"的部分，
        # 尾部留 len(end)-1 个字符等下一帧补齐（否则跨帧的结束标记永远认不出来）。
        keep = len(end) - 1
        if len(self._buf) > keep:
            self._body += self._buf[:-keep]
            self._buf = self._buf[-keep:]
        return False

    def _close(self, out: list, closed: bool = True) -> None:
        """闭合一个区域：校验通过则记成调用（尾巴原样放行），否则连标记一起原样放行。

        `closed=False` 表示"到流末仍未见到结束标记"：此时**不能**把结束标记补进放行内容
        —— 那些字符模型从未输出过，补上就是凭空造字。
        """
        calls, tail = parse_region(self._open[0], self._body, self._names)
        if calls:
            base = len(self._calls)
            for k, call in enumerate(calls):
                call["index"] = base + k
                if call["id"].startswith("call_txt_"):
                    call["id"] = f"call_txt_{base + k}"
            self._calls.extend(calls)
            if tail:
                # 无结束标记的区域（[TOOL_CALLS]）里，调用 JSON 之后的话必须原样放行
                out.append({"content": tail})
        else:
            end = (self._open[1] or "") if closed else ""
            out.append({"content": self._open[0] + self._body + end})
        self._open, self._body = None, ""

    def _flush(self, out: list) -> None:
        """原样吐出全部缓冲（在区域内则把标记补回去，保证一字不丢）。"""
        if self._open is not None:
            out.append({"content": self._open[0] + self._body + self._buf})
        elif self._buf:
            out.append({"content": self._buf})
        self._buf, self._body, self._open = "", "", None


# ─────────────────────────── 区域解析 ───────────────────────────
# 无结束标记的标记：其区域右边界由"最后一个成功解析的 JSON 值"决定
_OPEN_ENDED = frozenset({"[TOOL_CALLS]"})


def parse_region(start: str, body: str, names) -> tuple[list[dict], str]:
    """一个已闭合区域 → (调用列表, 未消费的正文尾巴)。

    尾巴只在**无结束标记**的区域（`[TOOL_CALLS]`）里可能非空：模型的调用 JSON 之后
    若还写了别的话，那些字必须原样放行 —— 否则就是"吞正文"，与不丢字的承诺相悖。
    有结束标记的区域整体属于该区域，尾巴恒为空串。
    """
    if start == "✿FUNCTION✿":
        return _parse_qwen_legacy(body, names), ""
    calls: list[dict] = []
    end = 0
    for obj, stop in _iter_json(body):
        calls.extend(_calls_from(obj, names, len(calls)))
        end = stop
    if start in _OPEN_ENDED:
        return calls, body[end:]
    return calls, ""


def _iter_json(text: str):
    """依次取出文本里的多个 JSON 值：产出 (值, 该值结束的偏移)。"""
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] not in "{[":
            i += 1
        if i >= n:
            return
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        yield obj, end
        i = end


def _calls_from(obj, names, base: int) -> list[dict]:
    """一段 JSON → 调用列表（容忍对象 / 数组 / {"tool_calls": [...]} 三种包装）。"""
    if isinstance(obj, dict) and isinstance(obj.get("tool_calls"), list):
        items = obj["tool_calls"]
    elif isinstance(obj, list):
        items = obj
    else:
        items = [obj]
    out: list[dict] = []
    for item in items:
        call = _one_call(item, names, base + len(out))
        if call:
            out.append(call)
    return out


def _one_call(item, names, index: int) -> Optional[dict]:
    """单条 → 内核口径的调用；`name` 不在已声明集合里就判否（安全阀 2）。"""
    if not isinstance(item, dict):
        return None
    fn = item.get("function") if isinstance(item.get("function"), dict) else item
    name = fn.get("name") or fn.get("tool_name") or ""
    if not name or (names and name not in names):
        return None
    args = fn.get("arguments")
    if args is None:
        args = fn.get("parameters")          # Llama 3 / 部分 GGUF 用 parameters
    if args is None:
        args = fn.get("tool_arguments")
    return {
        "index": index,
        "id": item.get("id") or f"call_txt_{index}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": args if isinstance(args, str)
            else json.dumps(args if args is not None else {}, ensure_ascii=False),
        },
    }


def _parse_qwen_legacy(body: str, names) -> list[dict]:
    """Qwen2.5 旧模板：`✿FUNCTION✿: name` + `✿ARGS✿: {...}`（裸文本，不是 JSON 块）。

    `body` 是剥掉 `✿FUNCTION✿` 之后的内容，形如 `: get_weather\n✿ARGS✿: {"city":"北京"}`。
    """
    name_m = _FN_RE.match(body)
    if not name_m:
        return []
    args = {}
    args_m = _ARGS_RE.search(body)
    if args_m:
        args = next((obj for obj, _ in _iter_json(args_m.group(1))), {}) or {}
    call = _one_call({"name": name_m.group(1), "arguments": args}, names, 0)
    return [call] if call else []


# ─────────────────────────── 事件流适配 ───────────────────────────
def text_tool_events(flt: TextToolFilter, ev: dict) -> list[dict]:
    """一个 provider 事件 → 过滤后的可下发事件列表。

    刻意做成**纯函数就地过滤**，而不是再包一层异步生成器：三个 provider 的事件循环
    都承载着"调用方 break 早退时不重复 aclose"的约束（见 ollama 模块文档的单生成器一节），
    多嵌一层会让那个已修复的重入问题回来。
    """
    if "content" in ev:
        return flt.feed(ev["content"])
    if "tool_calls" in ev:
        return flt.release() + [ev]
    if ev.get("done"):
        out = flt.finish()
        calls = flt.take_calls()
        if calls:
            _mark_text_calls(ev, len(calls))
            out.append({"tool_calls": calls})
        return out + [ev]
    return [ev]


def filter_events(events, names) -> list[dict]:
    """整段事件列表过一遍过滤器（非流式路径用，与流式共用同一份路由逻辑）。"""
    flt = TextToolFilter(names)
    out: list[dict] = []
    for ev in events:
        out.extend(text_tool_events(flt, ev))
    return out


def _mark_text_calls(done: dict, count: int) -> None:
    """把"这些调用是正文解析来的"如实标进 stats（改 finish_reason，但不掩盖原值）。

    改的理由：抽到的调用按 OpenAI 口径应表现为 `tool_calls`，否则按 finish_reason
    分支的调用方根本不会去执行工具。原值不丢 —— 记进 `finish_reason_vendor`，
    并用 `text_tool_calls` 标明这是文本解析来的。
    """
    stats = done.get("stats")
    if not isinstance(stats, dict):
        return
    mark_finish_tool_calls(stats)
    extra = stats.get("extra")
    if isinstance(extra, dict):
        extra["text_tool_calls"] = count


__all__ = ["MARKERS", "TextToolFilter", "declared_names", "parse_region",
           "text_tool_events", "filter_events"]
