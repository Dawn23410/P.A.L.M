"""显示层宿主：单 Python 进程编排多个透明 PyWebView 窗（壁纸 + 悬浮组件）。

职责：加载组件（.pwidget / .html / 文件夹包）→ 注入 PALM 桥 → 管理穿透与性能墙
→ 组件定位/布局 → 组件管理（启用/禁用/重载/卸载）→ 订阅推送 → 壁纸窗管理 → 安全退出。

窗口三类：
- 背景层（壁纸窗）：全屏，OS 级全穿透，z-order 最底
- 悬浮展示层（组件窗）：小窗，OS 级全穿透，z-order 桌面级（非置顶）
- 悬浮交互层（组件窗）：小窗，不穿透，z-order 桌面级（非置顶）

穿透模型：OS 级 WS_EX_TRANSPARENT 全有或全无，不使用 CSS pointer-events 部分穿透。
"""

import json
import logging
import os
import shutil
import threading

import webview

from .bridge import WidgetBridge
from .config import load_settings, save_settings, DEFAULT_SETTINGS
from .focus_monitor import FocusMonitor
from .loader import (load_widget_package, WidgetLoadError, split_widget_source,
                    write_widget_source, KNOWN_PROVIDERS)
from .providers import Providers
from .actions import register_default_actions
from .widget_settings import merge_widget_config, apply_widget_native, apply_widget_lock
from .win32_style import set_click_through, set_bottommost, get_screen_size
from .widget_persistence import WidgetStateMixin

LOG = logging.getLogger("palm.host")

WIDGET_DIR = os.path.join(os.path.dirname(__file__), "widgets")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


class WidgetHost:
    """编排组件窗、设置窗、穿透与性能墙。"""

    def __init__(self, owns_loop=True):
        self._owns_loop = owns_loop
        self._providers = Providers()
        self._bridge = WidgetBridge(self._providers, self)
        self._windows = {}            # widget_id -> Window
        self._win_lock = threading.RLock()  # 保护 _windows 的跨线程访问
        self._manifests = {}          # widget_id -> manifest
        self._sources = {}            # widget_id -> 源路径（重载用）
        self._settings = load_settings(SETTINGS_PATH)
        self._widget_settings = dict(self._settings.get("widgets", {}))
        self._settings_window = None
        self._editor_window = None
        self._actions = {}
        self._subscribers = {}        # provider -> set[widget_id]
        self._provider_subscribed = set()
        self._hidden_widgets = set()  # 专注模式下被隐藏的组件
        self._wallpaper_window = None  # 壁纸窗（背景层，全屏+穿透+置底）
        self._focus = FocusMonitor(self._on_focus_change)
        register_default_actions(self, WIDGET_DIR)

    # ---------- 设置持久化 ----------
    def get_settings(self):
        return dict(self._settings)

    def apply_settings(self, settings):
        """由设置窗写入并即时应用到所有窗。"""
        for key in DEFAULT_SETTINGS:
            if key in settings:
                self._settings[key] = settings[key]
        self._persist_settings()
        self.apply_click_through_all()
        self.apply_performance_wall()


    # ---------- 组件加载 ----------

    @staticmethod

    def _spawn(self, path, y_cursor):
        """加载单个组件包并建窗，单包失败不影响其他。"""
        try:
            manifest, html = load_widget_package(path)
        except (WidgetLoadError, ValueError, OSError) as exc:
            LOG.error("组件加载失败 %s：%s", path, exc)
            return
        widget_id = manifest["id"]
        self._sources[widget_id] = path
        self._create_widget_window(manifest, html, y_cursor)

    def _create_widget_window(self, manifest, html, y_cursor, x=None, y=None):
        widget_id = manifest.get("id", f"w{len(self._windows)}")
        saved = self._settings.get("positions", {}).get(widget_id)
        px = x if x is not None else (saved["x"] if saved else manifest.get("x", 40))
        py = y if y is not None else (saved["y"] if saved else manifest.get("y", y_cursor))
        width = int(manifest.get("width", 240))
        height = int(manifest.get("height", 160))
        try:
            window = webview.create_window(
                title=manifest.get("name", widget_id),
                html=html,
                x=int(px), y=int(py), width=width, height=height,
                transparent=True, frameless=True, on_top=False,
                js_api=self._bridge,
            )
        except Exception as exc:
            LOG.error("组件窗创建失败 %s：%s", widget_id, exc)
            return
        self._windows[widget_id] = window
        self._manifests[widget_id] = manifest
        self._providers.set_active(True)
        # 窗体显示后才分配原生 HWND；此事件在独立/集成两种模式下都会触发，
        # 保证穿透/透明度等 OS 级样式在句柄就绪后应用（集成模式不依赖 _after_start）。
        try:
            window.events.shown += lambda *_a: self._safe_apply_native(widget_id)
        except Exception as exc:
            LOG.warning("绑定窗体显示事件失败 %s：%s", widget_id, exc)
        LOG.info("已加载组件 %s (%s)", widget_id, manifest.get("name", ""))

    # ---------- 每组件通用设置（Rainmeter 式） ----------

    def apply_widget_native(self, widget_id):
        """把每组件通用设置应用到原生窗（穿透/透明度/置顶）与 DOM（锁定禁拖拽）。"""
        window = self._windows.get(widget_id)
        if not window:
            return
        cfg = self.effective_widget_config(widget_id)
        apply_widget_native(window, cfg)
        apply_widget_lock(window, cfg)

    def _safe_apply_native(self, widget_id):
        """events.shown 回调的安全包装，避免异常冒泡进 pywebview 事件循环。"""
        try:
            self.apply_widget_native(widget_id)
        except Exception as exc:
            LOG.warning("窗体显示后应用原生样式失败 %s：%s", widget_id, exc)




    # ---------- 穿透 ----------
    def set_click_through(self, widget_id, enabled):
        """组件侧请求切换穿透：写入每组件设置并即时应用（含 OS 级）。"""
        self._widget_settings.setdefault(widget_id, {})["clickThrough"] = bool(enabled)
        self._persist_widget_settings()
        self.apply_widget_native(widget_id)

    def apply_click_through_all(self):
        with self._win_lock:
            ids = list(self._windows.keys())
        for widget_id in ids:
            self.apply_widget_native(widget_id)

    # ---------- 定位与布局 ----------
    def move_window(self, widget_id, x, y):
        window = self._windows.get(widget_id)
        if window:
            try:
                window.move(int(x), int(y))
            except Exception as exc:
                LOG.warning("移动组件失败 %s：%s", widget_id, exc)

    def get_window_rect(self, widget_id):
        window = self._windows.get(widget_id)
        if not window:
            return {"x": 0, "y": 0, "width": 0, "height": 0}
        try:
            return {"x": int(getattr(window, "x", 0)),
                    "y": int(getattr(window, "y", 0)),
                    "width": int(getattr(window, "width", 0)),
                    "height": int(getattr(window, "height", 0))}
        except Exception:
            return {"x": 0, "y": 0, "width": 0, "height": 0}






    @staticmethod
    def _toggle_body_class(window, class_name, on):
        verb = "add" if on else "remove"
        try:
            window.evaluate_js(f"document.body.classList.{verb}('{class_name}')")
        except Exception as exc:
            LOG.warning("切换样式类失败 %s：%s", class_name, exc)

    # ---------- 性能墙（软预算） ----------
    def apply_performance_wall(self):
        """rich 组件允许数 = max(1, floor(gpuBudget × 组件总数))，超限降级。"""
        with self._win_lock:
            total = len(self._windows)
            items = list(self._windows.items())
        allowed_rich = max(1, int(self._settings["gpuBudget"] * max(1, total)))
        rich_count = 0
        for widget_id, window in items:
            if self._manifests.get(widget_id, {}).get("tier") == "rich":
                rich_count += 1
                self._toggle_body_class(window, "demoted", rich_count > allowed_rich)

    # ---------- 订阅推送 ----------
    def allowed_providers(self, widget_id):
        """返回组件被授权下发的 provider 集合（含 '*' 展开）。"""
        perms = self._manifests.get(widget_id, {}).get("permissions", ["*"])
        if "*" in perms:
            return set(KNOWN_PROVIDERS)
        return {p for p in perms if p in KNOWN_PROVIDERS}

    def subscribe(self, widget_id, provider):
        if provider not in self.allowed_providers(widget_id):
            LOG.warning("组件 %s 无权限订阅 %s，已忽略", widget_id, provider)
            return
        if provider not in self._provider_subscribed:
            self._provider_subscribed.add(provider)
            self._providers.subscribe(provider, lambda payload: self._on_provider_change(provider, payload))
        self._subscribers.setdefault(provider, set()).add(widget_id)

    def _on_provider_change(self, provider, payload):
        with self._win_lock:
            subs = list(self._subscribers.get(provider, set()))
        for widget_id in subs:
            self._push_to_window(widget_id, provider, payload)

    def _push_to_window(self, widget_id, provider, payload):
        # 专注模式下隐藏的组件不推送，避免无谓渲染（懒加载/可见性感知）。
        if widget_id in self._hidden_widgets:
            return
        with self._win_lock:
            window = self._windows.get(widget_id)
        if not window:
            return
        try:
            # payload 已是 provider 值的 JSON 串；包装成 {provider,value} 以匹配 shim._push。
            js_arg = '{"provider":' + json.dumps(provider) + ',"value":' + payload + '}'
            window.evaluate_js(f"window.__PALM_ON__ && window.__PALM_ON__({js_arg})")
        except Exception as exc:
            LOG.warning("推送失败 %s：%s", widget_id, exc)

    # ---------- Python 动作绑定 ----------


    # ---------- 组件管理 ----------

    def reload_all(self):
        """重载所有已启用组件（托盘「重载全部」用）。"""
        with self._win_lock:
            ids = list(self._windows.keys())
        for widget_id in ids:
            self.reload_widget(widget_id)
        return {"ok": True}

    def reload_widget(self, widget_id):
        source = self._sources.get(widget_id)
        if not source:
            return {"error": "找不到组件源"}
        rect = self.get_window_rect(widget_id)
        self._destroy_window(widget_id)
        try:
            manifest, html = load_widget_package(source)
        except (WidgetLoadError, ValueError, OSError) as exc:
            LOG.error("重载失败 %s：%s", widget_id, exc)
            return {"error": str(exc)}
        self._create_widget_window(manifest, html, 0, x=rect["x"], y=rect["y"])
        self._after_window_created(widget_id)
        return {"ok": True}

    def disable_widget(self, widget_id):
        if widget_id in self._windows:
            self._destroy_window(widget_id)
        if widget_id not in self._settings.setdefault("disabled", []):
            self._settings["disabled"].append(widget_id)
        self._persist_settings()
        return {"ok": True}

    def enable_widget(self, widget_id):
        if widget_id in self._settings.get("disabled", []):
            self._settings["disabled"].remove(widget_id)
            self._persist_settings()
        source = self._sources.get(widget_id)
        if source and widget_id not in self._windows:
            self._spawn(source, 40)
            self._after_window_created(widget_id)
        return {"ok": True}

    def remove_widget(self, widget_id):
        self._destroy_window(widget_id)
        source = self._sources.pop(widget_id, None)
        if source and os.path.exists(source):
            try:
                if os.path.isdir(source):
                    shutil.rmtree(source)
                else:
                    os.remove(source)
            except OSError as exc:
                LOG.warning("删除组件文件失败 %s：%s", source, exc)
        self._manifests.pop(widget_id, None)
        self._settings.get("positions", {}).pop(widget_id, None)
        self._persist_settings()
        return {"ok": True}


    def _destroy_window(self, widget_id):
        with self._win_lock:
            window = self._windows.pop(widget_id, None)
        if window:
            try:
                window.destroy()
            except Exception as exc:
                LOG.warning("销毁窗失败 %s：%s", widget_id, exc)

    def _after_window_created(self, widget_id):
        """新建/重载后恢复其穿透/透明度/锁定与降级状态。"""
        if not self._windows.get(widget_id):
            return
        self.apply_widget_native(widget_id)
        if self._manifests.get(widget_id, {}).get("tier") == "rich":
            self.apply_performance_wall()

    # ---------- 设置窗（open_settings 已移除，统一收进主程序设置；close_settings 保留为兼容桩） ----------

    # ---------- 组件源码读写（热重载） ----------


    # ---------- 编辑器窗 ----------
    def open_editor(self):
        if self._editor_window is not None:
            return
        self._editor_window = webview.create_window(
            title="组件编辑器", html=self._build_editor_html(),
            x=80, y=80, width=900, height=620,
            transparent=True, frameless=True, on_top=True, js_api=self._bridge,
        )
        # 登记到 _windows 使 shim 拖拽（get_window_rect/move_window）生效；
        # 不写 _manifests，故不会被 list_widgets 当组件列出。
        self._windows["__editor__"] = self._editor_window

    def close_editor(self):
        if self._editor_window is not None:
            try:
                self._editor_window.destroy()
            except Exception:
                pass
            self._windows.pop("__editor__", None)
            self._editor_window = None
        return True

    def _build_editor_html(self):
        from .editor_ui import build_editor_html
        return build_editor_html()

    # ---------- 壁纸窗（背景层） ----------
    def _create_wallpaper_window(self, html):
        """创建全屏壁纸窗：透明 + 无框 + 非置顶，显示后设 OS 级穿透 + 置底。"""
        sw, sh = get_screen_size()
        try:
            window = webview.create_window(
                title="PALM Wallpaper",
                html=html,
                x=0, y=0, width=sw, height=sh,
                transparent=True, frameless=True, on_top=False,
                js_api=self._bridge,
            )
        except Exception as exc:
            LOG.error("壁纸窗创建失败：%s", exc)
            return None
        # 窗体显示后才分配原生 HWND；此时才能设穿透与置底。
        try:
            window.events.shown += lambda *_a: self._safe_apply_wallpaper_native()
        except Exception as exc:
            LOG.warning("绑定壁纸窗显示事件失败：%s", exc)
        self._wallpaper_window = window
        LOG.info("壁纸窗已创建（%dx%d）", sw, sh)
        return window

    def _safe_apply_wallpaper_native(self):
        """壁纸窗显示后的安全包装：OS 级全穿透 + 置底。"""
        try:
            if self._wallpaper_window:
                set_click_through(self._wallpaper_window, True)
                set_bottommost(self._wallpaper_window)
        except Exception as exc:
            LOG.warning("壁纸窗原生样式应用失败：%s", exc)

    def _destroy_wallpaper_window(self):
        """销毁壁纸窗（内部方法）。"""
        if self._wallpaper_window:
            try:
                self._wallpaper_window.destroy()
            except Exception as exc:
                LOG.warning("销毁壁纸窗失败：%s", exc)
            self._wallpaper_window = None

    def set_wallpaper(self, html):
        """设置壁纸内容（HTML 字符串）。已有壁纸窗先销毁再重建。"""
        self._destroy_wallpaper_window()
        window = self._create_wallpaper_window(html)
        if window is None:
            return {"error": "壁纸窗创建失败"}
        # 持久化壁纸配置
        wp = self._settings.setdefault("wallpaper", {})
        wp["html"] = html
        wp["enabled"] = True
        self._persist_settings()
        return {"ok": True}

    def clear_wallpaper(self):
        """清除壁纸（销毁壁纸窗，恢复桌面原始壁纸）。"""
        self._destroy_wallpaper_window()
        wp = self._settings.setdefault("wallpaper", {})
        wp["enabled"] = False
        self._persist_settings()
        return {"ok": True}

    def _restore_wallpaper(self):
        """启动时从设置恢复壁纸（若上次退出时壁纸处于启用状态）。"""
        wp = self._settings.get("wallpaper", {})
        if wp.get("enabled") and wp.get("html"):
            self._create_wallpaper_window(wp["html"])

    # ---------- 专注模式（全屏自动隐藏） ----------
    def _on_focus_change(self, is_fullscreen):
        """前台进入/退出全屏时隐藏或恢复全部组件窗 + 壁纸窗。"""
        with self._win_lock:
            widget_ids = [wid for wid in self._windows if wid in self._manifests]
        if is_fullscreen:
            self._hidden_widgets.update(widget_ids)
        else:
            self._hidden_widgets.difference_update(widget_ids)
        for widget_id in widget_ids:
            with self._win_lock:
                window = self._windows.get(widget_id)
            if not window:
                continue
            try:
                if is_fullscreen:
                    window.hide()
                else:
                    window.show()
            except Exception as exc:
                LOG.warning("切换组件可见性失败 %s：%s", widget_id, exc)
        # 壁纸窗也跟随专注模式隐藏/恢复
        if self._wallpaper_window:
            try:
                if is_fullscreen:
                    self._wallpaper_window.hide()
                else:
                    self._wallpaper_window.show()
            except Exception as exc:
                LOG.warning("切换壁纸窗可见性失败：%s", exc)

    # ---------- 退出 ----------
    def request_quit(self):
        """由桥/托盘请求退出。

        独立模式（owns_loop）：停后台线程后用 webview.stop()（线程安全，终止唯一主
        循环，所有窗由框架统一销毁），避免跨线程直接 destroy 原生窗导致异常。
        集成模式：仅销毁组件窗与设置/编辑器窗，不终止主程序主循环。
        """
        LOG.info("收到退出请求")
        self._focus.stop()
        self._providers.stop()
        self._destroy_wallpaper_window()
        if self._owns_loop:
            webview.stop()
            return
        for widget_id in list(self._windows.keys()):
            self._destroy_window(widget_id)
        self.close_settings()
        self.close_editor()

    # ---------- 启动 ----------
    def _after_start(self):
        """GUI 循环就绪后初始化各窗的穿透与降级状态。"""
        self.apply_click_through_all()
        self.apply_performance_wall()

    def load_only(self):
        """集成模式启动：仅加载组件（建透明子窗），不启动主循环、不打开自身设置窗。

        由主程序的 webview.start() 统一驱动；须在 webview.start() 之前于主线程调用。
        """
        self._providers.start()
        self._focus.start(lambda: self._settings.get("focusMode", True))
        self.load_widgets()
        self._restore_wallpaper()

    def run(self):
        self._providers.start()
        self._focus.start(lambda: self._settings.get("focusMode", True))
        self.load_widgets()
        self._restore_wallpaper()
        webview.start(self._after_start)
