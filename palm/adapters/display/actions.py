"""内置 Python 动作：供组件经 PALM.runAction 绑定业务。

动作以 widget_id + payload 调用，返回 dict 作为桥结果。未知动作由宿主返回错误。
"""

import json
import os
import webbrowser


def register_default_actions(host, widget_dir):
    """把开箱即用的动作注册到宿主。"""

    def open_url(widget_id, payload):
        webbrowser.open(payload.get("url", "https://example.com"))
        return {"ok": True}

    def show_alert(widget_id, payload):
        window = host._windows.get(widget_id)
        if window:
            try:
                window.evaluate_js("alert(%s)" % json.dumps(payload.get("message", "hello")))
            except Exception:
                pass
        return {"ok": True}

    def launch_app(widget_id, payload):
        path = payload.get("path", "")
        if path and os.path.exists(path):
            if os.name == "nt":
                os.startfile(path)
            else:
                os.system('open "%s"' % path)
        return {"ok": True}

    def open_widgets_folder(widget_id, payload):
        if os.path.isdir(widget_dir):
            if os.name == "nt":
                os.startfile(widget_dir)
            else:
                os.system('open "%s"' % widget_dir)
        return {"ok": True}

    host.register_action("open_url", open_url)
    host.register_action("show_alert", show_alert)
    host.register_action("launch_app", launch_app)
    host.register_action("open_widgets_folder", open_widgets_folder)
    host.register_action("open_editor", lambda widget_id, payload: host.open_editor())
    host.register_action("close_editor", lambda widget_id, payload: host.close_editor())
