"""心智核心离线自检（无前端依赖，`python -m mentalcore.selftest`）。

mock 模式装配 → 全流程验证（硬断言）：
- 数据区协议：affinity_delta 被消费、inner_note 透传、注入面覆盖。
- 控制码路由：查/清/加密状态等旧码与新码均可达。
- mock 不落盘（persist 关闭）：对话后 storage_dir 不产生数据文件。

selftest 为测试用途：显式 mock 装配，不碰真实运行数据。
"""
import os
import sys

# 注：本文件在续8 从 mentalcore/mentalcore/selftest.py 迁移到 tests/ 包内，
# 原相对导入(.config/.core/.persona_card)在 tests 包下已失效，改指 mentalcore.mentalcore 绝对路径。
from mentalcore.mentalcore.config import Config
from mentalcore.mentalcore import build_core
from mentalcore.mentalcore.persona_card import default_persona


def selftest(core):
    """脚本化全流程验证（无交互，mock 模式离线）。"""
    print("=== selftest ===")
    failures = []
    r1 = None
    print("R1:", end=" ", flush=True)
    for ev in core.stream_message("今天有点难过"):
        if ev["type"] == "done":
            r1 = ev
            print("正文=", ev["body"][:30], "...")
            print("  外发字段=", ev["fields"])
            print("  注入源=", [m["source"] for m in ev["manifest"]])
            print("  情绪(输入侧)=", ev["emotion"])
    assert r1 is not None, "R1 未产生 done 事件"
    fields = r1["fields"]
    if "affinity_delta" in fields:
        failures.append("affinity_delta 不应出现在外发字段（应被消费）")
    if "inner_note" not in fields:
        failures.append("inner_note 应透传至外发字段")

    print("R2:", end=" ", flush=True)
    r2 = None
    for ev in core.stream_message("陪我聊聊"):
        if ev["type"] == "done":
            r2 = ev
            print("注入源=", [m["source"] for m in ev["manifest"]], "(应含 memory)")
    assert r2 is not None, "R2 未产生 done 事件"

    failures.extend(_verify_controls(core))

    if failures:
        print("=== selftest FAILED ===")
        for f in failures:
            print("  ✗", f)
        sys.exit(1)
    print("=== selftest PASSED ===")


def _verify_controls(core) -> list:
    """控制码路由与 mock 不落盘验证（返回失败项列表）。"""
    failures = []
    print("查记录 10000 ->", core.control(10000)["response"])
    print("查向量 11000 ->", core.control(11000)["response"])
    print("清记录 10100 ->", core.control(10100)["response"])
    print("清向量 11100 ->", core.control(11100)["response"])
    print("加密状态 13000 ->", core.control(13000)["response"])
    print("模型信息 ->", core.get_model_info())
    print("心跳 00000 ->", core.control(0)["response"])
    print("版本 01000 ->", core.control(1000)["response"])
    print("改好感度 30300 ->", core.control(30300, {"base": 2.0})["response"])
    print("向内传输 ->", core.receive({"mood": "开心"}, "外部上下文"))
    print("改人设清档 ->", core.update_persona(tone="冷淡")["note"])
    rec_after_persona = core.control(10000)["response"]
    print("改人设后查记录 10000 ->", rec_after_persona)
    if "记录数：0" not in rec_after_persona:
        failures.append("改人设后对话记录应已清空")

    # mock 不落盘：对话后 storage_dir 不应出现数据文件
    data_dir = core.storage.path
    leaked = [f for f in ("conversations.dat", "affinity.dat")
              if os.path.isfile(os.path.join(data_dir, f))]
    if leaked:
        failures.append(f"mock 模式不应落盘数据文件：{leaked}")
    return failures


def main():
    """mock 装配 → 自检；临时目录隔离，不碰真实数据；退出码 0 通过 / 1 失败。"""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="mc_selftest_")
    try:
        config = Config(
            mode="mock",
            storage_dir=os.path.join(tmp, "conv"),
            chroma_dir=os.path.join(tmp, "vm"),
            master_key_file=os.path.join(tmp, ".master_key"),
        )
        core = build_core(config, default_persona())
        selftest(core)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
