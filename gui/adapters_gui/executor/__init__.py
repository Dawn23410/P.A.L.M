"""GUI 自动化执行器包：由多个 mixin 组合而成，对外保持原 executor 模块的公共 API。

历史遗留单文件 executor.py(790 行) 已按职责拆分为：
  constants / state_mixin / locator_mixin / click_mixin / verify_mixin / vlc_mixin / prefetch_mixin
  core(AutomationExecutor 组合) / tool(RunAutomationTool) 。
外部仍通过 `from .executor import AutomationExecutor / RunAutomationTool` 使用，行为不变。
"""
from .core import AutomationExecutor, _EXECUTOR
from .tool import RunAutomationTool

__all__ = ["AutomationExecutor", "_EXECUTOR", "RunAutomationTool"]
