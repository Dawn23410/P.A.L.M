"""OCR 引流（最省 CPU、屯着批量、识别完立即释放）。

严格限定用途：识别「点击位置附近小区域」的文字标识，便于和 Atlas 按钮标签匹配
（对应校准闭环「识别点击位置标识利于匹配静态地图」）。不做坐标、不做全屏理解，
所以最省。与「后台树采集降级 OCR」完全解耦（采树兜底永不使用 OCR）。

策略：
- 仅在热点区那一小块截小图（非整屏），先屯进环形缓冲；
- 攒够 N 张 或 距上次触发空闲 T 秒，才用最低优先级单线程跑 OCR；
- 识别完立即 invalidate 引擎 + 删小图，释放占用。
"""
from __future__ import annotations

import ctypes
import logging
import os
import tempfile
import threading

_LOGGER = logging.getLogger(__name__)

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

_RING: list[dict] = []          # 环形缓冲：{bucket, path}
_ring_lock = threading.Lock()
_MAX_RING = 60
_BATCH = 20                     # 攒够 20 张触发
_IDLE_SECONDS = 300            # 或空闲 5 分钟触发
_last_run = 0.0


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """绝对窗口矩形；失败返回 None。"""
    if not _user32:
        return None
    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = _RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def submit_region(hwnd: int, rel_box: tuple[float, float, float, float],
                  bucket: str) -> bool:
    """把点击热点区小图截下并屯入缓冲（不立即 OCR）。失败静默返回 False。"""
    if not hwnd or not rel_box:
        return False
    rect = _window_rect(hwnd)
    if not rect:
        return False
    try:
        from PIL import Image, ImageGrab
        left, top, right, bottom = rect
        w, h = right - left, bottom - top
        nx, ny, nw, nh = rel_box
        x0 = int(left + max(nx - nw / 2, 0) * w)
        y0 = int(top + max(ny - nh / 2, 0) * h)
        x1 = int(left + min(nx + nw / 2, 1) * w)
        y1 = int(top + min(ny + nh / 2, 1) * h)
        if x1 <= x0 or y1 <= y0:
            return False
        shot = ImageGrab.grab((x0, y0, x1, y1))
        path = os.path.join(tempfile.gettempdir(),
                            f"palm_ocr_{abs(hash(bucket)) % 10**8}_{len(_RING)}.png")
        shot.save(path)
        with _ring_lock:
            _RING.append({"bucket": bucket, "path": path})
            while len(_RING) > _MAX_RING:
                _discard_oldest()
        return True
    except Exception as exc:
        _LOGGER.debug("OCR 区域截图失败: %s", exc)
        return False


def _discard_oldest() -> None:
    """丢弃最旧小图（环形缓冲溢出保护）。"""
    old = _RING.pop(0) if _RING else None
    if old:
        try:
            os.remove(old["path"])
        except Exception:
            pass


def maybe_run_ocr(force: bool = False) -> dict[str, list[str]]:
    """触发条件满足时跑 OCR（最低优先级单线程），返回 {bucket: [labels]}。

    force=True 忽略频率条件（测试/校准器兜底）。识别完立即 invalidate 引擎并删小图释放。
    """
    global _last_run
    with _ring_lock:
        batch = list(_RING)
        if not batch:
            return {}
        triggered = force or len(batch) >= _BATCH or (time_idle() >= _IDLE_SECONDS)
        if not triggered:
            return {}
        drained = batch[:_BATCH]
        del _RING[:len(drained)]
    labels: dict[str, list[str]] = {}
    try:
        _lower_thread_priority()
        from .ocr_engine import set_ocr_settings
        # 单线程最省 CPU 挡；跑完 invalidate 释放模型占用
        set_ocr_settings(cpu_intra_threads=1)
        eng = _get_ocr()
        for item in drained:
            try:
                res = eng(item["path"]) if eng else None
                texts = _extract_texts(res)
                labels.setdefault(item["bucket"], []).extend(texts)
            except Exception as exc:
                _LOGGER.debug("单图 OCR 失败: %s", exc)
            finally:
                try:
                    os.remove(item["path"])
                except Exception:
                    pass
        _release_engine()
    except Exception as exc:
        _LOGGER.warning("OCR 引流批量失败: %s", exc)
    _last_run = time_now()
    return labels


def time_idle() -> float:
    return time_now() - _last_run


def time_now() -> float:
    import time as _t
    return _t.time()


def _get_ocr():
    from .ocr_engine import get_ocr_engine
    return get_ocr_engine()


def _release_engine() -> None:
    """立即 invalidate 全局 OCR 引擎并强制回收，释放模型占用。"""
    try:
        import gc
        from .ocr_engine import set_ocr_settings
        set_ocr_settings(cpu_intra_threads=0)  # 触发 _invalidate_engine（全局置 None）
        import ocr_engine as _oe
        _oe._OCR_ENGINE = None
        gc.collect()
    except Exception:
        pass


def _extract_texts(res) -> list[str]:
    """从 RapidOCR 结果抽取文字（res=[boxes, texts, scores] 或 None）。"""
    if not res:
        return []
    try:
        texts = res[1]
        return [str(t).strip() for t in texts if str(t).strip()]
    except Exception:
        return []


def _lower_thread_priority() -> None:
    """当前线程降到最低优先级（Windows），把 CPU 抢占总量压到最小。"""
    try:
        _kernel32 = ctypes.windll.kernel32
        _kernel32.SetThreadPriority(_kernel32.GetCurrentThread(), -15)  # THREAD_PRIORITY_LOWEST
    except Exception:
        pass
