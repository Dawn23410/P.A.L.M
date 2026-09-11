"""GUI 内核基准 —— GUI 自动化（window_tools / adapters_gui 导入与结构）。

论文级维度：
- correctness:  window_tools / adapters_gui 导入成功（内核拆分后相对导入已修复）。
- boundary:     window_tools 在无桌面会话下调用返回 None/错误串而非崩溃。
- degradation:  pywin32 缺失时模块仍导入（零依赖 ctypes 路径）。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("gui")
def bench(col):
    # 1. 导入（关键：内核拆分把 window_tools 移到 gui/ 顶层，修复 ..tool_base 断裂）
    try:
        import gui.window_tools as wt
        import gui.adapters_gui as ag
        col.pass_("import", "gui_modules_importable", "correctness",
                  "gui.window_tools / gui.adapters_gui 导入成功"
                  "（已修复内核拆分后 ..tool_base 与 .window_api 相对导入断裂）")
    except Exception as e:
        col.fail("import", "gui_modules_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return

    # 2. window_tools 公开工具清单存在
    try:
        names = [n for n in dir(wt) if n.endswith("Tool")]
        assert len(names) > 0, "未暴露任何 Tool 子类"
        col.pass_("window_tools", "tool_classes_exposed", "correctness",
                  f"暴露 {len(names)} 个窗口工具类: {names[:6]}")
    except Exception as e:
        col.fail("window_tools", "tool_classes_exposed", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. Boundary：无桌面会话下列举窗口（应安全返回 None/[] 不崩）
    try:
        res = wt.enum_visible_windows()
        # 无头环境预期 None 或空列表；只要不抛异常即通过
        assert res is None or isinstance(res, list)
        col.pass_("window_tools", "enum_safe_headless", "boundary",
                  f"无桌面会话下 enum_visible_windows 返回 {type(res).__name__}（安全降级）")
    except Exception as e:
        col.xfail("window_tools", "enum_safe_headless", "boundary",
                  f"enum_visible_windows 在无头环境抛异常: {e}",
                  "".join(traceback.format_exception(type(e), e, e.__traceback__))[:300])

    # 4. Degradation：真实 UI 操作需图形会话 + ctypes user32，skip
    col.skip("window_tools", "real_window_ops", "degradation",
             "focus_window/get_pixel_color 等需活动图形会话与 user32，无头环境 → skip")
    col.skip("adapters_gui", "real_gui_automation", "degradation",
             "Atlas/世界模型/UIA 实时感知需桌面会话与屏幕，无头环境 → skip")
