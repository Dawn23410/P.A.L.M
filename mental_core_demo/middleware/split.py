"""LLM 回复拆分中间件（设计 §6.11 / §7.10）。

- 统一传输接口打包 + 外部解释器拆分（本 demo 内置解释器雏形）。
- 魔方内只拆好感度 delta（消费型，不放回）；其余未匹配字段统一打包外发。
- 输入输出同为「字段 + 正文」形式。
"""
import json
import re

# 字段注册表：consume=拆出来（消费后不放回）；未登记=外发（passthrough）
FIELD_REGISTRY = {
    "affinity_delta": "consume",
}


class ReplySplitter:
    """拆分器：从原始回复提取数据区，区分消费字段与外发字段。"""

    def __init__(self):
        self.raw_fields: dict = {}

    def split(self, raw: str):
        """返回 (正文, 外发字段, 消费字段)。"""
        body = raw
        fields: dict = {}
        match = re.search(r"\|\|DATA\|\|(.*?)\|\|END\|\|", raw, re.S)
        if match:
            try:
                fields = json.loads(match.group(1))
            except json.JSONDecodeError:
                fields = {}
            body = raw[:match.start()] + raw[match.end():]
        body = body.strip()

        out_fields: dict = {}
        consumed: dict = {}
        for key, value in fields.items():
            if FIELD_REGISTRY.get(key) == "consume":
                consumed[key] = value
            else:
                out_fields[key] = value
        self.raw_fields = fields
        return body, out_fields, consumed
