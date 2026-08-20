"""心智核心 CLI（前后端分离后，纯命令行演示）。

交互命令（以 / 开头）：
  /model            查看模型参数对外信息
  /manifest         查看最近一轮注入清单（开发者功能）
  /code <码|意图>   发送五位控制码，如 /code 10000 或 /code 查对话记录数
  /receive <正文>   向内传输：注入外部上下文（下一轮可见）
  /persona <k=v>    修改人设 → 触发防污染清档（聊天记录+向量归档）
  /help             帮助
  /exit             退出
普通输入视为对话文本，流式显示回复。
"""
import sys

from .core import MentalCore
from .mock_llm import MockLLM
from .persona_card import CharacterCard
from .transport import INTENT_ROUTES


def build_core(storage_path: str = "mental_core_demo/.data") -> MentalCore:
    persona = CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。",
        schedule=[("8-11", "晨读"), ("14-17", "画画")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
    llm = MockLLM(persona_name="梦瑶", tone="温柔轻快")
    return MentalCore(persona=persona, llm=llm, storage_path=storage_path)


def cmd_model(core: MentalCore):
    info = core.get_model_info()
    print("【模型信息】")
    for k, v in info.items():
        print(f"  {k}: {v}")


def cmd_manifest(core: MentalCore):
    m = core.last_manifest
    if not m:
        print("（暂无注入清单，先发一句话）")
        return
    print("【注入清单 · 开发者功能】")
    for item in m:
        tag = "固定" if item["fixed"] else "动态"
        avail = "可用" if item["available"] else "不可用(跳过)"
        print(f"  [{tag}|{avail}] {item['source']} "
              f"优先级{item['priority']} 约{item['chars']}字")


def cmd_control(core: MentalCore, arg: str):
    raw = arg.strip()
    code = None
    if raw.isdigit():
        code = int(raw)
    elif raw in INTENT_ROUTES:
        code = INTENT_ROUTES[raw]
    if code is None:
        print(f"无法解析控制码：{raw}（可填 5 位数字或意图名，如 查对话记录数）")
        return
    res = core.control(code)
    print(f"【控制码】{res['code']}")
    print(f"  响应：{res['response']}（响应码 {res['response_code']}）")


def cmd_receive(core: MentalCore, arg: str):
    body = arg.strip()
    if not body:
        print("用法：/receive <外部上下文正文>")
        return
    res = core.receive({"external_ctx": True}, body)
    print(f"已接收外部注入，下一轮对话可见。{res.get('note', '')}")


def cmd_persona(core: MentalCore, arg: str):
    parts = [p for p in arg.strip().split() if "=" in p]
    if not parts:
        print("用法：/persona tone=冷淡 或 /persona tagline=新简介")
        return
    fields = {}
    for p in parts:
        k, v = p.split("=", 1)
        fields[k.strip()] = v.strip()
    res = core.update_persona(**fields)
    print(f"【改人设】{res['note']}；修改字段：{', '.join(res['changed'])}")


def run_interactive(core: MentalCore):
    print("=== 心智核心 CLI（输入 /help 查看命令，/exit 退出）===")
    while True:
        try:
            line = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, rest = line[1:].partition(" ")
            cmd = cmd.lower()
            if cmd in ("exit", "quit", "q"):
                print("再见。")
                break
            if cmd == "help":
                print(__doc__)
            elif cmd == "model":
                cmd_model(core)
            elif cmd == "manifest":
                cmd_manifest(core)
            elif cmd == "code":
                cmd_control(core, rest)
            elif cmd == "receive":
                cmd_receive(core, rest)
            elif cmd == "persona":
                cmd_persona(core, rest)
            else:
                print(f"未知命令：/{cmd}（/help 查看）")
            continue
        # 普通对话：流式显示
        print("梦瑶> ", end="", flush=True)
        for ev in core.stream_message(line):
            if ev["type"] == "body":
                print(ev["text"], end="", flush=True)
            elif ev["type"] == "done":
                print()
                if ev["fields"]:
                    print(f"  （外发字段：{ev['fields']}）")


def selftest(core: MentalCore):
    """脚本化全流程验证（无交互）。"""
    print("=== selftest ===")
    print("R1:", end=" ", flush=True)
    for ev in core.stream_message("今天有点难过"):
        if ev["type"] == "done":
            print("正文=", ev["body"][:30], "...")
            print("  外发字段=", ev["fields"], "(应含 inner_note，不含 affinity_delta)")
            print("  注入源=", [m["source"] for m in ev["manifest"]])
            print("  情绪(输入侧)=", ev["emotion"])
    print("R2:", end=" ", flush=True)
    for ev in core.stream_message("陪我聊聊"):
        if ev["type"] == "done":
            print("注入源=", [m["source"] for m in ev["manifest"]], "(应含 memory)")
    print("查记录 10000 ->", core.control(10000)["response"])
    print("查向量 11000 ->", core.control(11000)["response"])
    print("清记录 10100 ->", core.control(10100)["response"])
    print("清向量 11100 ->", core.control(11100)["response"])
    print("再查记录 10000 ->", core.control(10000)["response"])
    print("加密状态 13000 ->", core.control(13000)["response"])
    print("模型信息 ->", core.get_model_info())
    print("向内传输 ->", core.receive({"mood": "开心"}, "外部上下文"))
    print("改人设清档 ->", core.update_persona(tone="冷淡")["note"])
    print("改人设后查记录 10000 ->", core.control(10000)["response"])
    print("=== selftest done ===")


def main():
    storage_path = sys.argv[1] if len(sys.argv) > 1 else "mental_core_demo/.data"
    core = build_core(storage_path)
    if "--selftest" in sys.argv:
        selftest(core)
    else:
        run_interactive(core)


if __name__ == "__main__":
    main()
