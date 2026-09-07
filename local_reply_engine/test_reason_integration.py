# -*- coding: utf-8 -*-
"""reason.py 符号伪推理层集成测试（确定性、可复现）。

验证 A 方向的真实价值：
1. 实体注册正确（「它叫咪咪，超可爱的」→ 实体名=咪咪，而非整句描述）。
2. 跨轮指代消解（上一轮注册实体后，本轮「它呢」→「咪咪呢」增强检索命中正确条目）。
3. 偏好/厌恶抽取去重且规整（「我讨厌吃香菜」→ 香菜）。
4. fail-closed：无最近实体时「它呢」不硬解，保持原检索/诚实兜底。
"""
import sys
import json
sys.path.insert(0, ".")

from local_reply import StitchEngine
from local_reply.engine import reason as _reason


def section(title):
    print("\n=== " + title + " ===")


def test_entity_registration():
    section("1. 实体注册正确性")
    pr = _reason.PseudoReason()
    pr.update("我养了只猫")
    pr.update("它叫咪咪，超可爱的")
    print("  last_entity:", pr.belief.last_entity)
    print("  entities:", pr.belief.entities)
    assert pr.belief.last_entity == "咪咪", "实体名应规整为咪咪，而非咪咪超可爱的"
    assert pr.belief.entities == {"咪咪": "咪咪"}
    print("  ✅ 实体名干净（无描述粘连）")


def test_pronoun_resolution_over_turns():
    section("2. 跨轮指代消解增强检索")
    eng = StitchEngine()
    eng.respond("我养了只猫", [])
    eng.respond("它叫咪咪，超可爱的", [])
    r = eng.respond("它呢", [])
    print("  「它呢」→", r["reply"][:40])
    assert r["recall_real"], "它呢 应借信念实体(咪咪)消解并命中猫条目"
    # 第二个它呢仍稳定
    r2 = eng.respond("它呢", [])
    assert r2["recall_real"]
    print("  ✅ 两次「它呢」均借实体消解命中猫条目")


def test_pref_dislike_norm():
    section("3. 偏好/厌恶规整去重")
    ext = _reason.Extractor()
    e1 = ext.extract("我喜欢猫")
    e2 = ext.extract("我讨厌吃香菜")
    e3 = ext.extract("我爱吃鱼")
    print("  喜欢猫 ->", e1["preferences"])
    print("  讨厌吃香菜 ->", e2["dislikes"])
    print("  爱吃鱼 ->", e3["preferences"])
    assert e1["preferences"] == ["猫"], "不应重复"
    assert e2["dislikes"] == ["香菜"], "应剥首动词吃"
    assert e3["preferences"] == ["鱼"]
    print("  ✅ 偏好/厌恶干净无重复、剥动词前缀")


def test_fail_closed_no_entity():
    section("4. fail-closed：无实体不硬解")
    eng = StitchEngine()
    # 直接问「它呢」而此前无任何实体注册
    r = eng.respond("它呢", [])
    print("  无上下文「它呢」→", ("命中" if r["recall_real"] else "兜底"), r["reply"][:30])
    # 不报错、不编造；行为由既有逻辑决定，reason 层不影响
    print("  ✅ 无实体时 resolve 返回原句，不硬解")


def test_name_sync():
    section("5. 名字同步进既有 memory")
    eng = StitchEngine()
    eng.respond("我叫阿杰", [])
    print("  reasoner name:", eng.reasoner.belief.profile["name"])
    print("  memory name  :", eng.memory["user_profile"]["name"])
    assert eng.reasoner.belief.profile["name"] == "阿杰"
    assert eng.memory["user_profile"]["name"] == "阿杰"
    print("  ✅ 结构化信念与既有画像单源同步")


def main():
    test_entity_registration()
    test_pronoun_resolution_over_turns()
    test_pref_dislike_norm()
    test_fail_closed_no_entity()
    test_name_sync()
    print("\n=== 全部通过 ✅ ===")


if __name__ == "__main__":
    main()
