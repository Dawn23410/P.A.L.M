"""LLM 回复拆分中间件（设计 §6.11 / §7.10）。

- 统一传输接口打包 + 外部解释器拆分（本内核内置解释器雏形）。
- ||DATA|| 载荷按字段过滤：消费型键（如 affinity_delta）不下发；其余透传外发。
- ||EXO|| 委派标记整体透传为 out_fields["exo"]（不面向用户、不消费）。
- 输入输出同为「字段 + 正文」形式。
"""
import json
import re

# ||DATA|| 载荷中消费型键（不纳入外发字段，仅内部消费）
CONSUME_KEYS = {"affinity_delta"}

# 标记名 → 处置策略：data=按字段过滤；exo=整体透传外骨骼委派
MARKER_POLICY = {
    "DATA": "data",
    "EXO": "exo",
}


class ReplySplitter:
    """拆分器：从原始回复提取数据区，区分消费字段、外骨骼委派与外发字段。"""

    def __init__(self):
        self.raw_fields: dict = {}

    def split(self, raw: str):
        """返回 (正文, 外发字段, 消费字段)；外骨骼委派存于 out_fields['exo']。"""
        body = raw
        matches = []
        for name in MARKER_POLICY:
            m = re.search(r"\|\|" + name + r"\|\|(.*?)\|\|END\|\|", raw, re.S)
            if m:
                matches.append((name, m))
        # 从后往前移除，避免删除靠后 span 时影响靠前 span 的索引
        for name, m in sorted(matches, key=lambda x: x[1].start(), reverse=True):
            body = body[:m.start()] + body[m.end():]

        consumed: dict = {}
        out_fields: dict = {}
        for name, m in matches:
            try:
                payload = json.loads(m.group(1))
            except json.JSONDecodeError:
                payload = None
            if MARKER_POLICY[name] == "data" and isinstance(payload, dict):
                for key, value in payload.items():
                    if key in CONSUME_KEYS:
                        consumed[key] = value
                    else:
                        out_fields[key] = value
            elif MARKER_POLICY[name] == "exo":
                out_fields["exo"] = payload

        body = body.strip()
        self.raw_fields = consumed
        return body, out_fields, consumed
