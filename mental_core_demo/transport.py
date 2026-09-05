"""双向传输包与五位控制码（设计 §6.11 / §7.13 / §7.14）。

输入输出统一为「字段 + 正文」形式：
- 字段 = 结构化数据区（供解释器拆分 / 注入）
- 正文 = 显示或内容文本
出向 = send_message 返回的传输包；入向 = receive 接收的传输包；两者同构。
"""


class TransportPacket:
    """传输包：字段(结构化数据区) + 正文(显示/内容文本)。"""

    def __init__(self, body: str, fields: dict = None):
        self.body = body
        self.fields = fields or {}

    def to_dict(self) -> dict:
        return {"body": self.body, "fields": self.fields}


# 控制码位次梯度（五位十进制，按位次由粗到细）
DOMAINS = {0: "系统", 1: "储存", 2: "记忆", 3: "情感", 4: "人格", 5: "对话", 9: "保留"}
ACTIONS = {0: "查", 1: "清", 2: "导出", 3: "改", 4: "启停", 9: "其他"}
PARAMS = {0: "请求", 1: "成功", 2: "失败"}

# D2 子类枚举：按域分类（每个域下自己的子类编号）
SUBCLASSES = {
    0: {0: "心跳", 1: "版本", 2: "重启"},
    1: {0: "对话记录", 1: "向量归档", 2: "导出包", 3: "加密状态"},
    2: {0: "短期记忆", 1: "长期记忆", 2: "核心记忆画像"},
    3: {0: "好感度档位", 1: "关系状态", 2: "情绪向量"},
    4: {0: "角色卡", 1: "动态数据", 2: "要素类型"},
    5: {0: "当前会话", 1: "历史会话"},
    9: {0: "保留"},
}

# D4 对象枚举（对象编号）
OBJECTS = {0: "全部", 1: "最近N条", 2: "指定编号"}

# 外部意图 → 控制码（供 CLI / 外部调用方直接映射，避免手算码值）
INTENT_ROUTES = {
    "查对话记录数": 10000,
    "清对话记录": 10100,
    "查向量归档数": 11000,
    "清向量归档": 11100,
    "查加密状态": 13000,
    "查模型信息": None,  # 走 get_model_info，非控制码
}


class ControlCode:
    """五位控制码：D1 域大类 / D2 子类 / D3 动作 / D4 对象 / D5 参数方向。"""

    def __init__(self, code: int):
        s = f"{code:05d}"
        self.code = code
        self.d1 = int(s[0])
        self.d2 = int(s[1])
        self.d3 = int(s[2])
        self.d4 = int(s[3])
        self.d5 = int(s[4])

    def domain_name(self) -> str:
        return DOMAINS.get(self.d1, "未知")

    def action_name(self) -> str:
        return ACTIONS.get(self.d3, "未知")

    def param_name(self) -> str:
        return PARAMS.get(self.d5, "参数")

    def subclass_name(self) -> str:
        return SUBCLASSES.get(self.d1, {}).get(self.d2, f"子类{self.d2}")

    def object_name(self) -> str:
        return OBJECTS.get(self.d4, f"对象{self.d4}")

    def describe(self) -> str:
        return (f"{self.domain_name()}·{self.subclass_name()}·{self.action_name()}"
                f"·{self.object_name()}·{self.param_name()}")

    @staticmethod
    def make(d1: int, d2: int, d3: int, d4: int, d5: int) -> "ControlCode":
        return ControlCode(d1 * 10000 + d2 * 1000 + d3 * 100 + d4 * 10 + d5)
