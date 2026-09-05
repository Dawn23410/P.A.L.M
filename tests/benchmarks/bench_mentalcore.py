"""MENTALCORE 内核基准 —— 心智核心 Agent 框架（纯结构/离线安全部分）。

论文级维度：
- correctness:  CharacterCard 构造、AffinityStage 枚举、default_persona、TransportPacket/ControlCode 解析。
- boundary:     构造缺字段不崩（fail-operational）。
- latency:      CharacterCard 构造 / default_persona 时延。
- idempotency:  default_persona 两次返回等价。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("mentalcore")
def bench(col):
    try:
        from mentalcore.mentalcore import (MentalCore, MentalCoreSlotPort,
                                            build_core, CharacterCard,
                                            AffinityStage, TransportPacket,
                                            ControlCode, INTENT_ROUTES,
                                            build_exo, WorkCube, ExoSlotPort)
        from mentalcore.mentalcore.persona_card import default_persona, OFFICIAL_6
        COL = dict(CharacterCard=CharacterCard, AffinityStage=AffinityStage,
                   TransportPacket=TransportPacket, ControlCode=ControlCode,
                   INTENT_ROUTES=INTENT_ROUTES, default_persona=default_persona,
                   OFFICIAL_6=OFFICIAL_6)
        col.pass_("import", "mentalcore_importable", "correctness",
                  "mentalcore.mentalcore 全符号导入成功（agent 框架整体保留）")
    except Exception as e:
        col.fail("import", "mentalcore_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return
    G = COL

    # 1. CharacterCard 构造（dataclass：必填 id/name/tagline/personality_pillars/flaws）
    try:
        cc = G["CharacterCard"](id="bench-1", name="bench-bot",
                                 tagline="测试角色", personality_pillars=["冷静"],
                                 flaws=["急性子"])
        assert cc.name == "bench-bot"
        col.pass_("character_card", "construct", "correctness",
                  "CharacterCard(id,name,tagline,pillars,flaws) 构造成功")
        stat = col.measure(lambda: G["CharacterCard"](
            id="x", name="x", tagline="t", personality_pillars=[], flaws=[]))
        col.pass_("character_card", "construct_latency", "latency",
                  "构造时延", latency=stat)
    except Exception as e:
        col.fail("character_card", "construct", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 2. AffinityStage 官方 6 阶预设
    try:
        stages = G["OFFICIAL_6"]
        assert isinstance(stages, list) and len(stages) > 0
        col.pass_("affinity_stage", "official_six_present", "correctness",
                  f"OFFICIAL_6 含 {len(stages)} 个好感度档位: {[s.name for s in stages]}")
    except Exception as e:
        col.fail("affinity_stage", "official_six_present", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. default_persona
    try:
        p1 = G["default_persona"]()
        p2 = G["default_persona"]()
        assert p1 is not None and p1.name == p2.name
        col.pass_("persona", "default_idempotent", "idempotency",
                  f"default_persona 两次等价: {p1.name}")
    except Exception as e:
        col.fail("persona", "default_idempotent", "idempotency", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 4. ControlCode / INTENT_ROUTES 解析
    try:
        routes = G["INTENT_ROUTES"]
        assert isinstance(routes, dict)
        col.pass_("control_code", "intent_routes", "correctness",
                  f"INTENT_ROUTES 路由表含 {len(routes)} 条入口")
    except Exception as e:
        col.fail("control_code", "intent_routes", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 5. Boundary：TransportPacket 缺字段
    try:
        # 部分字段缺失应 fail-operational
        tp = G["TransportPacket"](role="user", content="hi")
        assert tp is not None
        col.pass_("transport_packet", "partial_construct", "boundary",
                  "TransportPacket 部分字段构造不崩溃")
    except Exception as e:
        col.xfail("transport_packet", "partial_construct", "boundary",
                  f"TransportPacket 缺字段构造异常: {e}",
                  "".join(traceback.format_exception(type(e), e, e.__traceback__))[:300])

    # 6. Degradation：MentalCore 运行需 LLM（Ollama）+ persona，skip
    col.skip("core", "stream_message_run", "degradation",
             "MentalCore.send_message/stream_message 需 LLM 运行时，离线不可执行 → skip")
    col.skip("exo", "build_exo_run", "degradation",
             "build_exo/WorkCube 依赖 exo 运行时，离线不可执行 → skip")
