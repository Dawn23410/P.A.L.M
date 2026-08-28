"""run_automation 工具：把 LLM 规划的步骤数组交给执行器批量真实执行（规划/执行分离）。"""
from palm._core.tooling import Tool, ToolSpec

from .core import AutomationExecutor, _EXECUTOR

_RUN_DESC = (
    "接收一组 GUI 操作步骤并顺序真实执行（规划与执行分离的高效路径）。"
    "每步字段：action(click/type/press/hotkey/wait/check/close/verify 必填)；"
    "click 用 name/automation_id/control_type 定位控件（定向查找 ~10ms，失败自动 OCR 兜底），"
    "target 指定窗口标题或 hwnd；type 用 text；press 用 key；hotkey 用 keys 列表；"
    "wait 用 timeout 秒；check 用 automation_id 读取开关状态（状态先验，避免重复操作）；"
    "verify 用 name/automation_id/control_type 仅做廉价 UIA 存在性校验（不 OCR、不重建全量，"
    "供 LLM 确认状态而无需 describe_window）；"
    "close 关闭 target 窗口（用完清理）。"
    "click 可带 expect（动作后预期出现的控件名/automation_id 列表）或 action_label（驱动转移规律层"
    "高置信预测）：执行器点击后轮询校验预测控件出现，LLM 可据此跳过 describe_window 复查，省一轮调用；"
    "verify_timeout 控制轮询上限（默认 1s）；record 标记本次转移写入预测库（默认命中即记）。"
    "check 可带 stop_if（1=已开则停止后续，实现'目标已达成不重复操作'）。执行规范："
    "自己开的窗口用完 close；修改文档/表格类任务先保存（ctrl+s）再 close；"
    "默认步间延迟 0.2s（可 delay 覆盖）；失败即中止并返回诊断。"
)

def _build_run_params() -> dict:
    """run_automation 的 JSON Schema 参数（抽出为函数，保证单函数行数合规）。"""
    return {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "GUI 操作步骤数组，按顺序执行",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["click", "type", "press", "hotkey", "wait", "check", "close", "verify"]},
                        "name": {"type": "string", "description": "控件名称/标签子串（click 用）"},
                        "automation_id": {"type": "string", "description": "控件 automation_id（click 用）"},
                        "control_type": {"type": "string", "description": "控件类型过滤，如 Button"},
                        "target": {"type": "string", "description": "目标窗口标题子串；空取前台窗口"},
                        "text": {"type": "string", "description": "type 动作的输入文本"},
                        "key": {"type": "string", "description": "press 动作的按键名/键码，如 enter"},
                        "keys": {"type": "array", "items": {"type": "string"}, "description": "hotkey 组合键"},
                        "timeout": {"type": "number", "description": "wait 动作等待秒数"},
                        "stop_if": {"type": "number", "description": "check 动作：开关状态等于该值（1开/0关）则停止后续步骤"},
                        "expect": {"type": "array", "items": {"type": "string"}, "description": "click 后预期出现的控件名/automation_id 列表（驱动预测校验，省 LLM 复查）"},
                        "action_label": {"type": "string", "description": "click 动作标签，驱动转移规律层高置信预测校验"},
                        "verify_timeout": {"type": "number", "description": "expect/预测校验轮询上限秒数（默认 1）"},
                        "record": {"type": "boolean", "default": True, "description": "点击后是否将本次转移写入预测库（默认命中即记）"},
                        "delay": {"type": "number", "description": "本步后延迟秒数（默认 0.2）"},
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["steps"],
    }


class RunAutomationTool(Tool):
    """按 LLM 给出的步骤数组批量执行 GUI 操作（规划 → 执行分离）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_automation",
            description=_RUN_DESC,
            parameters=_build_run_params(),
            permission="desktop.control",
        )

    async def execute(self, steps: list | None = None) -> str:
        if not steps:
            return "未提供 steps。"
        return await _EXECUTOR.run(steps)

