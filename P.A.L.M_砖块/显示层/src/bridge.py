"""JS ↔ Python 桥：暴露给每个组件窗的 js_api 对象（window.pywebview.api）。

能力分三类：
1. 取数：get_provider（轮询）、subscribe（事件推送）
2. 交互：run_widget_action（绑 Python 业务）、set_click_through、各类定位/布局
3. 管理（设置窗/托盘调用）：list/reload/enable/disable/remove 组件、close_settings、quit_app
"""

import json


class WidgetBridge:
    """前端可调的全部桥能力，统一转发到宿主。"""

    def __init__(self, providers, host):
        self._providers = providers
        self._host = host

    # ---------- 取数 ----------
    def get_provider(self, widget_id=None, name="*"):
        """按组件声明的 permissions 过滤下发，未授权 provider 不返回。"""
        snap = self._providers.snapshot(name)
        if name != "*" or not widget_id:
            if name != "*" and widget_id:
                allowed = self._host.allowed_providers(widget_id)
                if name not in allowed:
                    return None
            return snap
        allowed = self._host.allowed_providers(widget_id)
        return {key: val for key, val in snap.items() if key in allowed}

    def subscribe(self, widget_id, provider):
        self._host.subscribe(widget_id, provider)
        return True

    # ---------- 交互 ----------
    def run_widget_action(self, widget_id, action, payload=None):
        return self._host.dispatch_action(widget_id, action, payload or {})

    def set_click_through(self, widget_id, enabled):
        self._host.set_click_through(widget_id, bool(enabled))
        return True

    def get_widget_settings(self, widget_id):
        return self._host.get_widget_settings(widget_id)

    def set_widget_settings(self, widget_id, settings):
        return self._host.set_widget_settings(widget_id, settings or {})

    def get_settings(self):
        return self._host.get_settings()

    def set_settings(self, settings):
        self._host.apply_settings(settings)
        return True

    def move_window(self, widget_id, x, y):
        self._host.move_window(widget_id, int(x), int(y))
        return True

    def get_window_rect(self, widget_id):
        return self._host.get_window_rect(widget_id)

    def save_position(self, widget_id, x, y):
        return self._host.save_position(widget_id, int(x), int(y))

    def save_layout(self, name):
        return self._host.save_layout(name)

    def apply_layout(self, name):
        return self._host.apply_layout(name)

    def list_layouts(self):
        return self._host.list_layouts()

    def delete_layout(self, name):
        return self._host.delete_layout(name)

    # ---------- 管理 ----------
    def list_widgets(self):
        return self._host.list_widgets()

    def reload_widget(self, widget_id):
        return self._host.reload_widget(widget_id)

    def enable_widget(self, widget_id):
        return self._host.enable_widget(widget_id)

    def disable_widget(self, widget_id):
        return self._host.disable_widget(widget_id)

    def remove_widget(self, widget_id):
        return self._host.remove_widget(widget_id)

    def get_widget_source(self, widget_id):
        return self._host.get_widget_source(widget_id)

    def save_widget_source(self, widget_id, source):
        return self._host.save_widget_source(widget_id, source)

    def close_settings(self):
        return self._host.close_settings()

    def open_editor(self):
        return self._host.open_editor()

    def close_editor(self):
        return self._host.close_editor()

    def quit_app(self):
        # 独立模式才真正退出；集成模式下仅关闭组件自身的设置/编辑器窗，不关主程序。
        if self._host._owns_loop:
            self._host.request_quit()
        else:
            self._host.close_settings()
            self._host.close_editor()
        return True

    @staticmethod
    def to_json(value):
        return json.dumps(value, ensure_ascii=False)
