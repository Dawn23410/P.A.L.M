"""提问工具：让 Agent 主动向用户提问，阻塞等待回答（human-in-the-loop）。

AI 自行选择提问方式（单选/多选/填空）、自定义题目、内容、选项。
前端会自动为选择题追加一个「其他（请说明）」选项 + 输入框，保证用户
总有自定义入口。实际阻塞与答案回传由编排层（core._handle_tool_events）
配合 QuestionHub 完成，本类仅声明工具规格供 LLM 调用。
"""
from __future__ import annotations

from palm._core.tooling import Tool


class AskUserTool(Tool):
    @property
    def spec(self):
        from palm._core.tooling import ToolSpec
        return ToolSpec(
            name="ask_user",
            description=(
                "向用户提问并阻塞等待回答。适用于需要用户决策/确认/补充信息的场景："
                "比如让用户从几个方案里选一个、收集用户偏好、确认某个操作是否执行。"
                "提问方式由你决定：question_type=single（单选，如四选一）、"
                "multiple（多选）、text（填空/自由输入）。可自定义题目(title)、"
                "内容说明(content)与选项(options)。前端会自动为选择题附加一个"
                "「其他（请说明）」选项+输入框，用户永远可以自定义回答。"
                "调用后流程会暂停，直到用户提交答案，答案会作为本次工具结果返回给你。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "问题题目，一句话点明要问什么",
                    },
                    "content": {
                        "type": "string",
                        "description": "问题内容/补充说明（可选），帮助用户理解背景",
                    },
                    "question_type": {
                        "type": "string",
                        "enum": ["single", "multiple", "text"],
                        "description": "提问方式：single=单选，multiple=多选，text=填空",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "自定义选项列表（single/multiple 用）；可留空，"
                                       "由你按题意给出 2-6 个选项；text 类型忽略此字段",
                    },
                },
                "required": ["title", "question_type"],
            },
        )

    async def execute(self, **kwargs) -> str:
        # 正常路径下不会执行到此处：编排层对 ask_user 做了特判并自行处理阻塞/回传。
        # 此兜底仅在非特判调用时返回提示，避免裸调用崩溃。
        return "[ask_user] 该工具由编排层拦截处理，不应被直接执行。"


ASK_TOOLS = [AskUserTool]
