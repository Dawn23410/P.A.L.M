"""可选系统托盘：有 pystray 则启用，否则降级（组件由主程序设置或自身管理）。

托盘提供：打开编辑器、重载全部组件、退出。所有动作 best-effort 并异常隔离，
创建窗口类操作从托盘线程发起，失败时仅记录日志，不影响主体运行。
"""

import logging
import threading

LOG = logging.getLogger("palm.tray")


def maybe_start_tray(host):
    """尝试启动托盘；缺依赖返回 None。"""
    try:
        import pystray  # noqa: F401
        from PIL import Image, ImageDraw  # noqa: F401
    except Exception:
        LOG.warning("未安装 pystray/Pillow，跳过系统托盘；可在主程序设置或组件自身管理退出。")
        return None
    try:
        import pystray
        from PIL import Image, ImageDraw
        icon = _build_icon(Image, ImageDraw)
        menu = pystray.Menu(
            pystray.MenuItem("打开编辑器", lambda: _safe(host.open_editor)),
            pystray.MenuItem("重载全部组件", lambda: _safe(host.reload_all)),
            pystray.MenuItem("退出", lambda icon_: _on_exit(host, icon_)),
        )
        tray = pystray.Icon("palm", icon, "P.A.L.M 组件", menu)
        threading.Thread(target=tray.run, daemon=True).start()
        LOG.info("系统托盘已启动")
        return tray
    except Exception as exc:
        LOG.warning("托盘启动失败：%s", exc)
        return None


def _safe(fn):
    """在独立线程执行，避免阻塞托盘循环；异常仅记录。"""
    threading.Timer(0, lambda: _run(fn)).start()


def _run(fn):
    try:
        fn()
    except Exception as exc:
        LOG.warning("托盘动作失败 %s：%s", getattr(fn, "__name__", fn), exc)


def _on_exit(host, icon):
    _safe(host.request_quit)
    try:
        icon.stop()
    except Exception:
        pass


def _build_icon(Image, ImageDraw):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=(59, 130, 246, 255))
    draw.text((22, 18), "P", fill=(255, 255, 255, 255))
    return img
