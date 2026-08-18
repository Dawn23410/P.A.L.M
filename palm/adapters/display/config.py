"""全局设置模型：默认值、校验、持久化。

设置字段：
- globalClickThrough: 全局点击穿透开关（Rainmeter 式）
- gpuBudget: 性能墙软预算（0.1~1），决定 rich 组件同时允许数
- focusMode: 专注模式，前台全屏时自动隐藏全部组件
- positions: { widget_id: {x, y} } 组件坐标持久化
- layouts: { 布局名: { widget_id: {x, y} } } 布局预设
- disabled: [widget_id] 被禁用的组件
"""

import json
import os

DEFAULT_SETTINGS = {
    "globalClickThrough": False,
    "gpuBudget": 0.3,
    "focusMode": True,
    "positions": {},
    "layouts": {},
    "disabled": [],
    "widgets": {},
    # 壁纸配置：html 内容、是否启用、渲染模式
    "wallpaper": {
        "enabled": False,
        "html": "",
        "mode": "html",       # html / video / image / web3d（后期扩展）
    },
}


def _clamp(data):
    """校验并收敛类型/范围，非法值回退默认，避免脏数据让宿主崩溃。"""
    out = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        for key in DEFAULT_SETTINGS:
            if key in data:
                out[key] = data[key]
    out["globalClickThrough"] = bool(out["globalClickThrough"])
    out["focusMode"] = bool(out["focusMode"])
    try:
        out["gpuBudget"] = min(1.0, max(0.1, float(out["gpuBudget"])))
    except (TypeError, ValueError):
        out["gpuBudget"] = 0.3
    out["positions"] = {k: v for k, v in (out.get("positions") or {}).items()
                        if isinstance(v, dict) and "x" in v and "y" in v}
    out["layouts"] = {k: v for k, v in (out.get("layouts") or {}).items() if isinstance(v, dict)}
    out["disabled"] = [i for i in (out.get("disabled") or []) if isinstance(i, str)]
    raw_widgets = out.get("widgets")
    out["widgets"] = raw_widgets if isinstance(raw_widgets, dict) else {}
    return out


def load_settings(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return _clamp(json.load(fh))
        except (OSError, ValueError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
