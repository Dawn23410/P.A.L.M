"""GUI 自动化指标记录器：每次 run_automation 的层级使用统计。

用途：逆推架构问题——L0 命中率低说明界面频繁变化/缓存策略失效；
L3/OCR 兜底占比高说明 UIA 覆盖不足；stop_if 频繁触发说明 LLM 规划冗余。
数据落盘 Data/gui_metrics/YYYY-MM-DD.jsonl（JSON Lines 追加式，不覆盖历史）
+ _session.json（会话聚合快照，直接看整体分布）。线程锁保证并发安全，
落盘失败静默（指标绝不能拖垮执行器主流程）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from palm._core.paths import brick_local

_LOGGER = logging.getLogger(__name__)


def _data_dir() -> str:
    """指标落盘目录：砖内 data/gui_metrics/，砖可随意移动。"""
    return brick_local(__file__, "data", "gui_metrics")


def new_run_stats() -> dict:
    """每次 run 的独立统计容器（字段固定，便于跨 run 聚合对比）。"""
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "software": "",            # 窗口 exe 归一化 id（winword/excel 等）
        "steps_total": 0, "steps_done": 0,
        "outcome": "",             # ok / failed / interrupted / timeout
        "elapsed_ms": 0,
        "levels": {},              # {L0: n, L2: n, L3: n, fulltree: n}
        "cache_hits": 0,           # 与运行时坐标缓存一致（=L0 直点）
        "prefetch_hits": 0,        # 预取线程定位结果被消费
        "redraw_retries": 0,       # 界面重绘导致的定向重试
        "actions": {},             # {click: n, type: n, ...}
        "stop_if_fired": 0,
        "mouse_interrupt": False,
        "timeout_fired": False,
        "failures": [],            # 失败步骤摘要（定位失败/动作异常）
    }


class GuiMetrics:
    """线程安全的指标收集器：单行 JSONL 追加 + 进程内会话聚合。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session = {
            "runs": 0, "levels": {}, "actions": {},
            "cache_hits": 0, "prefetch_hits": 0, "stop_if_fired": 0,
            "l0_rate": 0.0,  # L0 直点占所有已定位点击的比例（架构健康度核心指标）
        }

    def record(self, stats: dict) -> None:
        """落盘一条 run 记录并更新会话聚合；任何失败都静默。"""
        try:
            day = time.strftime("%Y-%m-%d")
            path = os.path.join(_data_dir(), f"{day}.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(stats, ensure_ascii=False) + "\n")
        except Exception as exc:
            _LOGGER.warning("指标落盘失败（不影响执行）: %s", exc)
            return
        with self._lock:
            s = self._session
            s["runs"] += 1
            s["cache_hits"] += stats["cache_hits"]
            s["prefetch_hits"] += stats["prefetch_hits"]
            s["stop_if_fired"] += stats["stop_if_fired"]
            for lv, n in stats["levels"].items():
                s["levels"][lv] = s["levels"].get(lv, 0) + n
            for ac, n in stats["actions"].items():
                s["actions"][ac] = s["actions"].get(ac, 0) + n
            located = sum(s["levels"].values())
            s["l0_rate"] = round(s["levels"].get("L0", 0) / located, 3) if located else 0.0
            self._dump_session()

    def _dump_session(self) -> None:
        """会话聚合快照：today=今日累计（重放 jsonl，跨进程）+ process=本进程聚合。

        jsonl 是唯一事实源，session 只是便于直接查看的快照；重放文件很小。
        """
        try:
            today = {"runs": 0, "levels": {}, "actions": {},
                     "cache_hits": 0, "prefetch_hits": 0, "stop_if_fired": 0,
                     "l0_rate": 0.0}
            day_path = os.path.join(_data_dir(), time.strftime("%Y-%m-%d") + ".jsonl")
            if os.path.exists(day_path):
                with open(day_path, encoding="utf-8") as fh:
                    for line in fh:
                        row = json.loads(line)
                        today["runs"] += 1
                        today["cache_hits"] += row["cache_hits"]
                        today["prefetch_hits"] += row["prefetch_hits"]
                        today["stop_if_fired"] += row["stop_if_fired"]
                        for lv, n in row["levels"].items():
                            today["levels"][lv] = today["levels"].get(lv, 0) + n
                        for ac, n in row["actions"].items():
                            today["actions"][ac] = today["actions"].get(ac, 0) + n
                located = sum(today["levels"].values())
                today["l0_rate"] = round(today["levels"].get("L0", 0) / located, 3) if located else 0.0
            path = os.path.join(_data_dir(), "_session.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"today": today, "process": self._session},
                          fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._session)


METRICS = GuiMetrics()
