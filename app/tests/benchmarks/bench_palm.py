"""PALM CORE 内核基准 —— 核心（eventbus / container / emotion / token_estimate / build_app / net fail-closed）。

论文级维度：
- correctness:  事件总线订阅/发布/审计快照；容器服务解析；token 估算；情绪检测。
- boundary:     未注册网卡 → 外网请求 fail-closed 抛 NetworkForbidden。
- latency:      emit/subscribe 时延；token_estimate 时延。
- idempotency:  同文本 token 估算稳定。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("palm")
def bench(col):
    try:
        from palm._core.eventbus import (subscribe, emit, unsubscribe,
                                          audit_snapshot, subscriber_count)
        from palm._core.container import container, Container
        from palm._core.token_estimate import estimate_tokens
        from palm._core.emotion import detect, build_emotion_hint
        from palm._core.net import request, NetworkForbidden
        from palm.bootstrap.app import build_app
        COL = dict(subscribe=subscribe, emit=emit, unsubscribe=unsubscribe,
                   audit_snapshot=audit_snapshot, subscriber_count=subscriber_count,
                   container=container, estimate_tokens=estimate_tokens,
                   detect=detect, build_emotion_hint=build_emotion_hint,
                   request=request, NetworkForbidden=NetworkForbidden,
                   build_app=build_app)
        col.pass_("import", "palm_submodules_importable", "correctness",
                  "palm._core.* / palm.bootstrap.app 导入成功")
    except Exception as e:
        col.fail("import", "palm_submodules_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return
    G = COL

    # 1. 事件总线
    try:
        received = []
        handler = lambda e: received.append(e)
        G["subscribe"]("entity.deleted", handler)
        assert G["subscriber_count"]("entity.deleted") >= 1
        G["emit"]("entity.deleted", {"id": "x1"})
        snap = G["audit_snapshot"]()
        assert isinstance(snap, (list, dict))
        assert any(r.get("id") == "x1" for r in received), "事件未投递"
        col.pass_("eventbus", "publish_subscribe", "correctness",
                  f"订阅→发布→投递成功，收到 {len(received)} 条；审计快照可用")
        G["unsubscribe"]("entity.deleted", handler)  # 签名 unsubscribe(event_type, handler)
        assert G["subscriber_count"]("entity.deleted") == 0
        col.pass_("eventbus", "unsubscribe_works", "correctness",
                  "unsubscribe(event_type, handler) 后订阅计数归零")
        stat = col.measure(lambda: G["emit"]("bench.ping", {"t": 1}))
        col.pass_("eventbus", "emit_latency", "latency", "emit 时延分布", latency=stat)
    except Exception as e:
        col.fail("eventbus", "publish_subscribe", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 2. 容器服务解析（缺失降级为 None）
    try:
        # 不存在的服务应返回 None 而非抛异常（graceful degradation）
        assert G["container"].get("__no_such_service__") is None
        col.pass_("container", "missing_service_none", "degradation",
                  "查询未注册服务返回 None（不崩溃）")
    except Exception as e:
        col.fail("container", "missing_service_none", "degradation", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. token 估算
    try:
        n1 = G["estimate_tokens"]("你好世界 hello world")
        n2 = G["estimate_tokens"]("你好世界 hello world")
        assert n1 > 0 and n1 == n2
        col.pass_("token_estimate", "deterministic", "correctness",
                  f"中文+英文混合估算={n1} tokens，幂等")
        stat = col.measure(lambda: G["estimate_tokens"]("x" * 500))
        col.pass_("token_estimate", "latency", "latency",
                  "500 字符估算时延", latency=stat)
    except Exception as e:
        col.fail("token_estimate", "deterministic", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 4. 情绪检测（桩，确定性）
    try:
        emo = G["detect"]("我今天很开心")
        assert isinstance(emo, dict)
        hint = G["build_emotion_hint"]("我有点难过")
        assert isinstance(hint, str)
        col.pass_("emotion", "detect_and_hint", "correctness",
                  f"detect→{emo}；hint 生成成功")
    except Exception as e:
        col.fail("emotion", "detect_and_hint", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 5. 边界：net fail-closed（未注册网卡）
    try:
        from palm._core.net import is_card_present
        raised = False
        try:
            G["request"]("GET", "https://example.com")
        except G["NetworkForbidden"]:
            raised = True
        if raised:
            col.pass_("net", "fail_closed_offline", "boundary",
                      "未注册网卡时外网请求抛 NetworkForbidden（fail-closed 安全）")
        elif is_card_present():
            col.pass_("net", "fail_closed_offline", "boundary",
                      "网卡已注册（环境已注入执行器），request 合法放行")
        else:
            col.fail("net", "fail_closed_offline", "boundary",
                     "未注册网卡且未抛 NetworkForbidden → fail-open 安全缺陷",
                     root_cause="net facade 未装配网卡执行器时未拒绝")
    except Exception as e:
        col.fail("net", "fail_closed_offline", "boundary", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 6. build_app 装配（缺失底座降级不崩溃）
    # 依赖 pydantic（离线环境缺失）→ 标记 SKIP 并追溯根因，不计入 FAIL。
    try:
        import importlib
        importlib.import_module("pydantic")
        c = G["build_app"]()
        assert c is not None
        col.pass_("bootstrap", "build_app_idempotent_degrade", "degradation",
                  "build_app() 在依赖齐备环境下仍返回容器且不抛异常")
    except ModuleNotFoundError as e:
        col.skip("bootstrap", "build_app_idempotent_degrade", "degradation",
                 f"build_app 依赖 pydantic（离线缺失）：{e} → skip")
    except Exception as e:
        col.fail("bootstrap", "build_app_idempotent_degrade", "degradation", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
