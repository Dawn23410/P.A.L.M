"""display 砖：桌面壁纸与悬浮组件统一渲染层。

基于 PyWebView + WebView2，单进程管理多透明窗口：
- 背景层：全屏壁纸窗（OS 级全穿透，z-order 最底）
- 悬浮展示层：小窗组件（OS 级全穿透，z-order 最顶）
- 悬浮交互层：小窗组件（不穿透，z-order 最顶）

穿透模型：OS 级全有或全无（WS_EX_TRANSPARENT），不使用 CSS pointer-events 部分穿透。

集成模式：主程序在 webview 循环就绪后调用 set_host() 注入 WidgetHost 实例，
REST 端点经 _host 代理到宿主方法；WidgetHost 自身在 GUI 线程管理窗口生命周期。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry

_LOG = logging.getLogger("palm.display.brick")

router = APIRouter(prefix="/api/display", tags=["display"])

# WidgetHost 实例（懒初始化，由主程序在 webview 循环就绪后注入）。
_host = None


def set_host(host):
    """主程序在初始化显示层后注入 WidgetHost 实例。"""
    global _host
    _host = host
    _LOG.info("WidgetHost 已注入 display 砖")


def get_host():
    """获取当前 WidgetHost 实例（可能为 None，表示尚未初始化）。"""
    return _host


# ---------- 组件管理端点 ----------

@router.get("/widgets", dependencies=[Depends(require_api_token)])
def api_list_widgets():
    """列出所有已加载的组件。"""
    if not _host:
        return {"widgets": [], "error": "display host not initialized"}
    return {"widgets": _host.list_widgets()}


@router.post("/widgets/{widget_id}/reload", dependencies=[Depends(require_api_token)])
def api_reload_widget(widget_id: str):
    """重载指定组件（从磁盘重新读取源码并重建窗口）。"""
    if not _host:
        return {"error": "display host not initialized"}
    return _host.reload_widget(widget_id)


@router.post("/widgets/{widget_id}/enable", dependencies=[Depends(require_api_token)])
def api_enable_widget(widget_id: str):
    """启用指定组件（从禁用列表移除并重新加载）。"""
    if not _host:
        return {"error": "display host not initialized"}
    return _host.enable_widget(widget_id)


@router.post("/widgets/{widget_id}/disable", dependencies=[Depends(require_api_token)])
def api_disable_widget(widget_id: str):
    """禁用指定组件（销毁窗口并加入禁用列表）。"""
    if not _host:
        return {"error": "display host not initialized"}
    return _host.disable_widget(widget_id)


@router.post("/widgets/{widget_id}/click-through", dependencies=[Depends(require_api_token)])
def api_set_click_through(widget_id: str, payload: dict):
    """切换组件的点击穿透状态（OS 级 WS_EX_TRANSPARENT）。"""
    if not _host:
        return {"error": "display host not initialized"}
    enabled = bool(payload.get("enabled", False))
    _host.set_click_through(widget_id, enabled)
    return {"ok": True, "widget_id": widget_id, "clickThrough": enabled}


# ---------- 壁纸管理端点 ----------

@router.post("/wallpaper", dependencies=[Depends(require_api_token)])
def api_set_wallpaper(payload: dict):
    """设置壁纸内容（HTML 字符串，由 WebView2 渲染）。"""
    if not _host:
        return {"error": "display host not initialized"}
    html = payload.get("html", "")
    if not html:
        return {"error": "缺少 html 参数"}
    return _host.set_wallpaper(html)


@router.delete("/wallpaper", dependencies=[Depends(require_api_token)])
def api_clear_wallpaper():
    """清除壁纸（销毁壁纸窗口，恢复桌面原始壁纸）。"""
    if not _host:
        return {"error": "display host not initialized"}
    return _host.clear_wallpaper()


# ---------- 设置端点 ----------

@router.get("/settings", dependencies=[Depends(require_api_token)])
def api_get_settings():
    """获取显示层全局设置。"""
    if not _host:
        return {"error": "display host not initialized"}
    return _host.get_settings()


@router.post("/settings", dependencies=[Depends(require_api_token)])
def api_set_settings(settings: dict):
    """更新显示层全局设置并即时应用。"""
    if not _host:
        return {"error": "display host not initialized"}
    _host.apply_settings(settings)
    return {"ok": True}


# ---------- 布局端点 ----------

@router.get("/layouts", dependencies=[Depends(require_api_token)])
def api_list_layouts():
    """列出所有已保存的布局预设。"""
    if not _host:
        return {"layouts": [], "error": "display host not initialized"}
    return {"layouts": _host.list_layouts()}


@router.post("/layouts/{name}", dependencies=[Depends(require_api_token)])
def api_save_layout(name: str):
    """保存当前所有组件坐标为命名布局。"""
    if not _host:
        return {"error": "display host not initialized"}
    return {"ok": _host.save_layout(name)}


@router.put("/layouts/{name}", dependencies=[Depends(require_api_token)])
def api_apply_layout(name: str):
    """应用命名布局（一键切换组件排布）。"""
    if not _host:
        return {"error": "display host not initialized"}
    return {"ok": _host.apply_layout(name)}


@router.delete("/layouts/{name}", dependencies=[Depends(require_api_token)])
def api_delete_layout(name: str):
    """删除命名布局。"""
    if not _host:
        return {"error": "display host not initialized"}
    return {"ok": _host.delete_layout(name)}


# ---------- 砖块注册 ----------

brick = Brick(
    manifest=BrickManifest(
        name="display",
        title="显示层",
        description="桌面壁纸与悬浮组件统一渲染层，基于 PyWebView + WebView2",
        bus_type="pcie",
    ),
    router=router,
    capabilities={
        "set_host": set_host,
        "get_host": get_host,
    },
)
registry.register(brick)