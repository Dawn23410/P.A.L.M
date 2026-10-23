from __future__ import annotations

import json
import logging
import os
import shutil

from .config import load_settings, save_settings
from .widget_settings import merge_widget_config, apply_widget_native

LOG = logging.getLogger("palm.host")
WIDGET_DIR = os.path.join(os.path.dirname(__file__), "widgets")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")


class WidgetStateMixin:
    """WidgetHost 的状态持久化/设置/布局方法组（拆分自 host.py，逻辑零改动）。"""

    def _persist_settings(self):
        try:
            save_settings(SETTINGS_PATH, self._settings)
        except OSError as exc:
            LOG.warning("设置保存失败：%s", exc)


    def load_widgets(self):
        """扫描组件目录，逐个创建透明置顶窗（禁用的跳过）。"""
        if not os.path.isdir(WIDGET_DIR):
            LOG.warning("组件目录不存在：%s", WIDGET_DIR)
            return
        y_cursor = 40
        for name in sorted(os.listdir(WIDGET_DIR)):
            path = os.path.join(WIDGET_DIR, name)
            widget_id = self._derive_id(path)
            if widget_id in self._settings.get("disabled", []):
                LOG.info("跳过禁用组件：%s", widget_id)
                continue
            self._spawn(path, y_cursor)
            y_cursor += 200


    def _derive_id(path):
        if path.endswith(".pwidget"):
            return os.path.splitext(os.path.basename(path))[0]
        if path.endswith(".html"):
            return os.path.splitext(os.path.basename(path))[0]
        return os.path.basename(path.rstrip("/\\"))


    def effective_widget_config(self, widget_id):
        """合并 manifest 默认 + 存储的每组件设置；全局穿透为 OR 叠加。"""
        manifest = self._manifests.get(widget_id, {})
        stored = self._widget_settings.get(widget_id)
        cfg = merge_widget_config(stored, manifest)
        if self._settings.get("globalClickThrough"):
            cfg["clickThrough"] = True
        return cfg


    def get_widget_settings(self, widget_id):
        return self.effective_widget_config(widget_id)


    def set_widget_settings(self, widget_id, patch):
        if not isinstance(patch, dict):
            return {"error": "patch 必须是对象"}
        cfg = self._widget_settings.setdefault(widget_id, {})
        for key in ("clickThrough", "locked", "alwaysOnTop"):
            if key in patch:
                cfg[key] = bool(patch[key])
        if "opacity" in patch:
            try:
                cfg["opacity"] = min(1.0, max(0.0, float(patch["opacity"])))
            except (TypeError, ValueError):
                pass
        self._persist_widget_settings()
        self.apply_widget_native(widget_id)
        return self.effective_widget_config(widget_id)


    def _persist_widget_settings(self):
        self._settings["widgets"] = self._widget_settings
        self._persist_settings()


    def save_position(self, widget_id, x, y):
        self._settings.setdefault("positions", {})[widget_id] = {"x": int(x), "y": int(y)}
        self._persist_settings()
        return True


    def save_layout(self, name):
        if not name:
            return False
        positions = self._settings.get("positions", {})
        self._settings.setdefault("layouts", {})[name] = dict(positions)
        self._persist_settings()
        return True


    def apply_layout(self, name):
        layout = self._settings.get("layouts", {}).get(name)
        if not layout:
            return False
        for widget_id, pos in layout.items():
            window = self._windows.get(widget_id)
            if window:
                try:
                    window.move(int(pos["x"]), int(pos["y"]))
                except Exception:
                    pass
        self._settings["positions"] = dict(layout)
        self._persist_settings()
        return True


    def list_layouts(self):
        return list(self._settings.get("layouts", {}).keys())


    def delete_layout(self, name):
        self._settings.get("layouts", {}).pop(name, None)
        self._persist_settings()
        return True


    def register_action(self, name, handler):
        self._actions[name] = handler


    def dispatch_action(self, widget_id, action, payload):
        handler = self._actions.get(action)
        if not handler:
            return {"error": f"unknown action: {action}"}
        try:
            return handler(widget_id, payload) or {"ok": True}
        except Exception as exc:
            LOG.error("动作执行失败 %s：%s", action, exc)
            return {"error": str(exc)}


    def close_settings(self):
        if self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass
            self._settings_window = None
        return True


    def get_widget_source(self, widget_id):
        source = self._sources.get(widget_id)
        if not source or not os.path.exists(source):
            return {"error": "找不到组件源"}
        try:
            return split_widget_source(source)
        except (WidgetLoadError, ValueError, OSError) as exc:
            return {"error": str(exc)}


    def save_widget_source(self, widget_id, source):
        src_path = self._sources.get(widget_id)
        if not src_path or not os.path.exists(src_path):
            return {"error": "找不到组件源"}
        try:
            write_widget_source(src_path, source)
        except (WidgetLoadError, ValueError, OSError) as exc:
            LOG.error("写入组件源码失败 %s：%s", widget_id, exc)
            return {"error": str(exc)}
        reload_out = self.reload_widget(widget_id)
        if "error" in reload_out:
            return reload_out
        return {"ok": True, "reloaded": widget_id}

    def list_widgets(self):
        out = []
        with self._win_lock:
            items = list(self._manifests.items())
            active_ids = set(self._windows.keys())
        for widget_id, manifest in items:
            out.append({
                "id": widget_id,
                "name": manifest.get("name", widget_id),
                "enabled": widget_id in active_ids,
                "tier": manifest.get("tier", "lite"),
            })
        return out


    def install_widget(self, source_path):
        """把外部组件包复制到组件目录并加载，返回新组件 id。"""
        if not os.path.exists(source_path):
            return {"error": "源路径不存在"}
        widget_id = self._derive_id(source_path)
        dest = os.path.join(WIDGET_DIR, os.path.basename(source_path.rstrip("/\\")))
        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, dest)
            else:
                shutil.copy2(source_path, dest)
        except OSError as exc:
            return {"error": f"复制失败：{exc}"}
        if widget_id in self._settings.get("disabled", []):
            self._settings["disabled"].remove(widget_id)
            self._persist_settings()
        self._spawn(dest, 40)
        self._after_window_created(widget_id)
        return {"ok": True, "id": widget_id}

