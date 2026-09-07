# -*- coding: utf-8 -*-
"""P.A.L.M 模型 API · 本地对话引擎 FastAPI 服务。

路由前缀统一为 /p.a.l.m/models/api（P.A.L.M 模型类模块接口规范）。
档位独立端口：full=10000 / balanced=10001 / lite=10002（规范要求 ≥10000）。
引擎按 tier 惰性创建并加锁复用，进程内共享；加载异常记录原因供心跳上报。
支持自定义语料目录（PALM_CORPUS_DIR / PALM_DATA_DIR 或 /reload 热替换）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine import engine as _ENGINE_MOD
from .engine.engine import StitchEngine, CONFIDENCE_THRESHOLDS

API_PREFIX = "/p.a.l.m/models/api"
TIER_PORTS = {"full": 10000, "balanced": 10001, "lite": 10002}
# 心跳状态码：0=就绪 1=未就绪(服务在但引擎未加载) 2=异常(error 带原因)
CODE_READY, CODE_NOT_READY, CODE_ERROR = 0, 1, 2
_ENGINE_HERE = os.path.dirname(os.path.abspath(_ENGINE_MOD.__file__))
DEFAULT_CORPUS_DIR = os.environ.get("PALM_CORPUS_DIR")
DEFAULT_DATA_DIR = os.environ.get("PALM_DATA_DIR")

_STARTED_AT = time.time()
_ENGINES: dict[str, StitchEngine] = {}
_ENGINE_ERRORS: dict[str, str] = {}
_ENGINE_CORPUS: dict[str, str] = {}
_LAST_CALL: dict[str, dict] = {}
_ENGINE_LOCKS: dict[str, threading.Lock] = {}
_SERVER_TIER = "full"
_LOCK = threading.Lock()
_VALID_TIERS = ("full", "balanced", "lite")


def _tier_lock(tier: str) -> threading.Lock:
    """每个档位一把锁，串行化对该引擎共享状态（memory/recent_replies）的访问。"""
    lk = _ENGINE_LOCKS.get(tier)
    if lk is None:
        with _LOCK:
            lk = _ENGINE_LOCKS.get(tier)
            if lk is None:
                lk = threading.Lock()
                _ENGINE_LOCKS[tier] = lk
    return lk


def _resolve_corpus(tier: str, corpus_dir: str | None,
                    data_dir: str | None) -> tuple[str | None, str | None]:
    """corpus 解析顺序：显式 > 已加载档位记忆 > 环境变量 > 引擎内置。"""
    c = corpus_dir or _ENGINE_CORPUS.get(tier) or DEFAULT_CORPUS_DIR
    d = data_dir or DEFAULT_DATA_DIR
    return c, d


def _load_engine(tier: str, corpus_dir: str | None = None,
                 data_dir: str | None = None) -> StitchEngine:
    """真正构建引擎；异常落 _ENGINE_ERRORS 供心跳上报。"""
    c, d = _resolve_corpus(tier, corpus_dir, data_dir)
    try:
        eng = StitchEngine(tier=tier, corpus_dir=c, data_dir=d)
    except Exception as exc:  # noqa: BLE001
        _ENGINE_ERRORS[tier] = f"{type(exc).__name__}: {exc}"
        raise
    _ENGINE_ERRORS.pop(tier, None)
    if c:
        _ENGINE_CORPUS[tier] = c
    return eng


def _get_engine(tier: str) -> StitchEngine:
    """按档位惰性获取引擎（线程安全，双检锁，进程内复用）。"""
    if tier not in _VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier 必须是 {_VALID_TIERS}")
    eng = _ENGINES.get(tier)
    if eng is not None:
        return eng
    with _LOCK:
        eng = _ENGINES.get(tier)
        if eng is None:
            eng = _load_engine(tier)
            _ENGINES[tier] = eng
    return eng


def preload_engine(tier: str) -> tuple[bool, str | None]:
    """启动预热；返回 (是否成功, 失败原因)。"""
    try:
        _get_engine(tier)
        return True, None
    except HTTPException as exc:
        return False, str(exc.detail)
    except Exception as exc:  # noqa: BLE001
        return False, _ENGINE_ERRORS.get(tier, str(exc))


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=200, description="用户输入")
    history: list[tuple[str, str]] = Field(
        default=[], max_length=20, description="多轮历史 [(user, reply), ...]")
    tier: str = Field(default=None, description="full | balanced | lite，缺省用服务档位")


class ReloadIn(BaseModel):
    tier: str = Field(default="full", description="要重载的档位")
    corpus_dir: str = Field(default=None, description="新语料目录（mengyao_hq_part*.jsonl）")
    data_dir: str = Field(default=None, description="新索引缓存目录（缺省随引擎）")


def _hb_payload(tier: str) -> dict:
    """按档位生成心跳状态码与详情（不做任何加载，纯只读）。"""
    if tier in _ENGINE_ERRORS:
        return {"code": CODE_ERROR, "status": "error", "ready": False,
                "error": _ENGINE_ERRORS[tier]}
    if tier in _ENGINES:
        return {"code": CODE_READY, "status": "ready", "ready": True,
                "error": None}
    return {"code": CODE_NOT_READY, "status": "not_ready", "ready": False,
            "error": "引擎尚未加载（首请求或 --preload 后变 ready）"}


def _dir_size_mb(path: str | None) -> float:
    if not path or not os.path.isdir(path):
        return 0.0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return round(total / 1024 / 1024, 1)


def _win_metrics() -> tuple[int, float] | None:
    """返回 (RSS 字节, 进程 CPU 秒)，非 Windows 或失败返回 None。"""
    try:
        k = ctypes.windll.kernel32
        # 现代 Windows: psapi 转发到 kernel32 的 K32* 别名，直接取 K32 名最稳
        meminfo = getattr(k, "K32GetProcessMemoryInfo", None) or getattr(
            ctypes.windll.psapi, "GetProcessMemoryInfo", None)

        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        k.GetCurrentProcess.restype = wt.HANDLE
        meminfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        meminfo.restype = ctypes.c_bool
        k.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME)]
        k.GetProcessTimes.restype = ctypes.c_bool
        p = PMC()
        p.cb = ctypes.sizeof(p)
        if not meminfo(k.GetCurrentProcess(), ctypes.byref(p), ctypes.sizeof(p)):
            return None
        ft_k = wt.FILETIME(); ft_u = wt.FILETIME()
        ft_c = wt.FILETIME(); ft_e = wt.FILETIME()
        if not k.GetProcessTimes(k.GetCurrentProcess(), ctypes.byref(ft_c),
                                 ctypes.byref(ft_e), ctypes.byref(ft_k),
                                 ctypes.byref(ft_u)):
            return p.WorkingSetSize, 0.0
        cpu_ns = ((ft_k.dwHighDateTime << 32) | ft_k.dwLowDateTime) + \
                 ((ft_u.dwHighDateTime << 32) | ft_u.dwLowDateTime)
        return p.WorkingSetSize, cpu_ns / 1e7
    except Exception:
        return None


def _metrics_payload() -> dict:
    """内存/存储/CPU 性能开销快照（进程级 + 各就绪档位）。"""
    uptime = round(time.time() - _STARTED_AT, 1)
    win = _win_metrics()
    rss_mb = round(win[0] / 1024 / 1024, 1) if win else None
    cpu_pct = round(win[1] / uptime * 100, 1) if win else None
    weights = os.path.join(_ENGINE_HERE, "models", "weights")
    tiers = {}
    for t, eng in _ENGINES.items():
        fp = None
        try:
            fp = eng._corpus_fp()
        except Exception:
            pass
        tiers[t] = {
            "records": len(getattr(eng, "records", []) or []),
            "mode": getattr(eng, "mode", None),
            "corpus_fp": fp,
            "corpus_dir": _ENGINE_CORPUS.get(t),
        }
    return {
        "uptime_s": uptime,
        "process": {
            "rss_mb": rss_mb, "cpu_pct": cpu_pct,
            "threads": threading.active_count(),
        },
        "storage_mb": {
            "corpus_default": _dir_size_mb(os.path.join(_ENGINE_HERE, "corpus")),
            "data_default": _dir_size_mb(os.path.join(_ENGINE_HERE, "data")),
            "weights": _dir_size_mb(weights),
            "custom_corpus": _dir_size_mb(DEFAULT_CORPUS_DIR),
        },
        "tiers": tiers,
        "tier_errors": dict(_ENGINE_ERRORS),
        "last_call": dict(_LAST_CALL),
    }


def create_app(default_tier: str = "full") -> FastAPI:
    global _SERVER_TIER
    _SERVER_TIER = default_tier if default_tier in _VALID_TIERS else "full"
    app = FastAPI(title="P.A.L.M Model API - Mengyao Local Engine",
                  version="1.2")

    @app.get(API_PREFIX + "/heartbeat")
    def heartbeat(tier: str = None):
        """心跳：状态码区分 就绪(0)/未就绪(1)/异常(2)，异常带原因。"""
        t = tier if tier in _VALID_TIERS else _SERVER_TIER
        payload = _hb_payload(t)
        return {
            "code": payload["code"], "status": payload["status"],
            "ready": payload["ready"], "error": payload["error"],
            "tier": t, "port": TIER_PORTS.get(t),
            "service": "palm.models.mengyao_local",
            "api_prefix": API_PREFIX,
            "tiers_ready": sorted(_ENGINES.keys()),
            "tier_errors": dict(_ENGINE_ERRORS),
            "corpus_dir": _ENGINE_CORPUS.get(t),
            "thresholds": CONFIDENCE_THRESHOLDS,
            "uptime_s": round(time.time() - _STARTED_AT, 1),
        }

    @app.post(API_PREFIX + "/chat")
    def chat(body: ChatIn):
        """对话：返回回复、置信度、模式与延迟（按档位加锁，串行化共享状态访问）。"""
        tier = body.tier if body.tier else _SERVER_TIER
        with _tier_lock(tier):
            t0 = time.perf_counter()
            eng = _get_engine(tier)
            try:
                r = eng.respond(body.text, body.history)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if isinstance(r, dict):
            _LAST_CALL[tier] = {
                "confidence": r.get("confidence"), "mode": r.get("mode"),
                "latency_ms": latency_ms, "fallback": bool(r.get("suggest_llm")),
            }
            return {"reply": r.get("reply"), "confidence": r.get("confidence"),
                    "mode": r.get("mode"), "tier": tier,
                    "latency_ms": latency_ms}
        return {"reply": str(r), "confidence": None, "mode": "unknown",
                "tier": tier, "latency_ms": latency_ms}

    @app.get(API_PREFIX + "/stats")
    def stats(tier: str = None):
        """上一轮调用状态（置信度/延迟/是否兜底）+ 服务运行信息。"""
        t = tier if tier in _VALID_TIERS else _SERVER_TIER
        return {"tier": t, "last_call": _LAST_CALL.get(t),
                "uptime_s": round(time.time() - _STARTED_AT, 1)}

    @app.post(API_PREFIX + "/reset")
    def reset(tier: str = None):
        """清空指定档位引擎的会话记忆（recent_replies / queries）。"""
        t = tier if tier in _VALID_TIERS else _SERVER_TIER
        with _tier_lock(t):
            eng = _get_engine(t)
            mem = getattr(eng, "memory", None)
            if isinstance(mem, dict):
                if isinstance(mem.get("recent_replies"), list):
                    mem["recent_replies"] = []
                if isinstance(mem.get("queries"), list):
                    mem["queries"] = []
        _LAST_CALL.pop(t, None)
        return {"tier": t, "reset": True}

    @app.post(API_PREFIX + "/reload")
    def reload(body: ReloadIn):
        """热替换档位语料：用新 corpus_dir 重建引擎并原子替换，旧缓存按语料指纹隔离。"""
        t = body.tier if body.tier in _VALID_TIERS else _SERVER_TIER
        if body.corpus_dir and not glob.glob(
                os.path.join(body.corpus_dir, "mengyao_hq_part*.jsonl")):
            raise HTTPException(status_code=400,
                                detail=f"语料目录无 mengyao_hq_part*.jsonl: {body.corpus_dir}")
        with _tier_lock(t):
            try:
                new_eng = _load_engine(t, body.corpus_dir, body.data_dir)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500,
                                    detail=f"重建失败: {exc}") from exc
            old = _ENGINES.get(t)
            _ENGINES[t] = new_eng
            _LAST_CALL.pop(t, None)
        return {"tier": t, "corpus_dir": _ENGINE_CORPUS.get(t),
                "records": len(new_eng.records), "mode": new_eng.mode,
                "reloaded": True, "old_freed": old is not None}

    @app.get(API_PREFIX + "/metrics")
    def metrics():
        """内存(RSS)/CPU/存储(I/O)开销快照：进程级 + 各就绪档位。"""
        return _metrics_payload()

    return app
