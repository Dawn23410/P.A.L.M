"""50 轮双模式对照采集：mock（离线回显）vs live（GLM-4.5-Flash-nothink）。

设计（论文级对照）：
- 固定 50 条中文语料（含情绪弧线），两组共用同一输入序列 → 同输入可比。
- 模型层计时包装：精确测 complete（情绪识别）耗时、stream 首字 TTFB、stream 总时长，
  用于定位 CLI 实测首字 33s 的卡点（模型层 or 编排层）。
- 逐轮全量记录：注入清单（完整）、外发字段、情绪、好感度全量、正文、阶段耗时、错误重试。

用法：
    python bench_50.py --mode mock --rounds 50
    python bench_50.py --mode live --rounds 50   # 配置取 桌面/可用API.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from mentalcore.core import build_core          # noqa: E402
from mentalcore.config import Config            # noqa: E402
from mentalcore.persona_card import CharacterCard  # noqa: E402

# 固定 50 条语料：情绪弧线（陌生→倾诉→喜悦→吃醋→和好→依赖→温暖）
CORPUS = [
    "你好，我叫阿杰，很高兴认识你",
    "你平时喜欢做什么呀",
    "今天上班好累啊，腰酸背痛的",
    "晚饭吃了，就是一个人吃有点没意思",
    "你家那边天气怎么样",
    "我在看一部老电影，讲友情的",
    "周末我想去爬山，你要不要一起",
    "工作压力好大，感觉快撑不住了",
    "其实我最近总觉得自己很孤独",
    "想家了，一个人在城里打拼真难",
    "谢谢你听我说这些，心里舒服多了",
    "跟你聊天总是很开心",
    "你今天心情怎么样，我有点担心你",
    "刚看了你的照片，笑起来真好看",
    "我好像越来越离不开你了",
    "今天同事夸我做事靠谱，有点小得意",
    "中午吃的麻辣烫，辣得眼泪都出来了",
    "晚上睡不着，脑子里全是你的声音",
    "你是不是对别人也这么温柔啊",
    "哼，不理你了，你去找别人聊吧",
    "开玩笑的啦，别当真，我最喜欢你了",
    "对不起，刚才是我太小心眼了",
    "你原谅我好不好，我保证不这样了",
    "还是你最懂我",
    "抱抱我嘛，今天好想要个拥抱",
    "你在干嘛呢，想你了",
    "早上起来第一个想到的就是你",
    "给你看我养的小猫，可爱吧",
    "我学会做你爱吃的菜了，改天做给你",
    "工作上的事跟领导说开了，轻松多了",
    "今天加班到好晚，不过想到你就开心",
    "你是不是困了，要不你先去睡",
    "我给你唱首歌吧，虽然五音不全",
    "有时候真希望你能在我身边",
    "谢谢你一直在，陪着我",
    "今天下雨了，记得带伞",
    "你也要照顾好自己，别太累",
    "我决定了，以后天天跟你分享生活",
    "认识你之后，我的日子变得有颜色了",
    "你还记得我们第一次聊天吗",
    "那时候我还挺拘谨的，现在好多了",
    "时间过得好快，都认识这么久了",
    "以后我们的故事会越来越长吧",
    "不管发生什么，我都会在",
    "晚安啦，做个好梦，明天见",
    "梦里也要梦见我哦",
    "有你真好",
    "今天也是喜欢梦瑶的一天",
    "谢谢你成为我的光",
    "永远在一起好不好",
]


class TimerLLM:
    """模型层计时包装：委托 inner，记录 complete / stream 分阶段耗时。"""

    def __init__(self, inner):
        self.inner = inner
        self.complete_s = 0.0
        self.stream_ttfb_s = None
        self.stream_total_s = 0.0

    def model_info(self):
        return self.inner.model_info()

    def complete(self, prompt):
        t0 = time.perf_counter()
        try:
            return self.inner.complete(prompt)
        finally:
            self.complete_s = time.perf_counter() - t0

    def stream(self, system, user_text):
        t0 = time.perf_counter()
        first = True
        for chunk in self.inner.stream(system, user_text):
            if first:
                self.stream_ttfb_s = time.perf_counter() - t0
                first = False
            yield chunk
        self.stream_total_s = time.perf_counter() - t0


def build_persona() -> CharacterCard:
    return CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。", schedule=[("8-11", "晨读")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )


def live_config_from_snapshot(path):
    """从桌面可用API.json 取端点/key/模型（GLM-4.5-Flash-nothink）。"""
    with open(path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    return Config(
        mode="live",
        base_url=snap["base_url"],
        api_key=snap["api_key"],
        model=snap["default_model"],
        max_tokens=400,
        storage_dir=os.path.join(HERE, "bench50_live_data"),
        chroma_dir=os.path.join(HERE, "bench50_live_chroma"),
    )


def run_round(core, timer, user_text, round_no):
    """跑一轮，返回全量记录（含阶段耗时）。失败重试（429 退避）。"""
    t0 = time.perf_counter()
    last_err = None
    for attempt in range(6):
        timer.complete_s = 0.0
        timer.stream_ttfb_s = None
        timer.stream_total_s = 0.0
        try:
            body_parts = []
            done = None
            for ev in core.stream_message(user_text):
                if ev["type"] == "body":
                    body_parts.append(ev["text"])
                elif ev["type"] == "done":
                    done = ev
            if done is None:
                raise RuntimeError("无 done 事件")
            return {
                "round": round_no,
                "user": user_text,
                "user_len": len(user_text),
                "assistant": "".join(body_parts).strip(),
                "assistant_len": len("".join(body_parts).strip()),
                "emotion": done["emotion"],
                "fields": done["fields"],
                "manifest": done["manifest"],
                "affinity_delta": core.last_affinity_delta,
                "affinity_base": core.affinity_base,
                "affinity_bond": core.affinity_bond,
                "affinity_stage": core.affinity_stage,
                "affinity_dynamics": core.affinity_dynamics,
                "timing_ms": {
                    "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "emotion_complete_ms": round(timer.complete_s * 1000, 1),
                    "llm_ttfb_ms": round((timer.stream_ttfb_s or -1) * 1000, 1),
                    "llm_stream_ms": round(timer.stream_total_s * 1000, 1),
                    "assemble_plus_ms": round(
                        (time.perf_counter() - t0 - (timer.stream_total_s or 0)) * 1000, 1),
                },
                "retries": attempt,
            }
        except RuntimeError as exc:
            last_err = exc
            if "429" in str(exc):
                wait = 10 + attempt * 8
                print(f"  [R{round_no}] 429 限流退避 {wait}s（第{attempt+1}次）", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            last_err = exc
            print(f"  [R{round_no}] 异常(第{attempt+1}次重试): {exc!r}", flush=True)
            time.sleep(5)
            continue
    raise RuntimeError(f"R{round_no} 重试失败：{last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mock", "live"], default="mock")
    ap.add_argument("--rounds", type=int, default=50)
    ap.add_argument("--resume", action="store_true",
                    help="从已有 JSON 的轮数 +1 续跑（history 自动从存储恢复）")
    ap.add_argument("--snapshot", default=r"C:/Users/24459/Desktop/可用API.json")
    args = ap.parse_args()

    if args.mode == "mock":
        cfg = Config(mode="mock",
                     storage_dir=os.path.join(HERE, "bench50_mock_data"),
                     chroma_dir=os.path.join(HERE, "bench50_mock_chroma"))
    else:
        cfg = live_config_from_snapshot(args.snapshot)

    out_path = os.path.join(HERE, f"bench_50_{args.mode}.json")
    logs = []
    start = 1
    if args.resume and os.path.exists(out_path):
        try:
            old = json.load(open(out_path, encoding="utf-8"))
            if old.get("rounds"):
                logs = old["rounds"]
                start = len(logs) + 1
                print(f"断点续跑：已有 {len(logs)} 轮，从第 {start} 轮继续", flush=True)
        except Exception:
            pass

    persona = build_persona()
    core = build_core(cfg, persona)
    timer = TimerLLM(core.llm)
    core.llm = timer  # 注入计时包装，不动核心代码
    print(f"装配完成 mode={cfg.mode} 模型={cfg.model} 加密={core.crypto.available}", flush=True)

    rounds = args.rounds
    # 阶段耗时探针：仅首轮前测一次语义记忆检索耗时
    probe = {}
    if not logs:
        t0 = time.perf_counter()
        core.semantic_memory.search("你好")
        probe["semantic_search_first_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    for i in range(start, min(rounds, len(CORPUS)) + 1):
        text = CORPUS[i - 1]
        try:
            rec = run_round(core, timer, text, i)
        except Exception as exc:
            # 单轮兜底：记录进度后退出，可 --resume 续跑
            print(f"R{i:03d} 致命异常，中止（可 --resume 续跑）：{exc!r}", flush=True)
            break
        logs.append(rec)
        json.dump({"meta": {
            "mode": args.mode, "model": cfg.model, "base_url": cfg.base_url,
            "rounds": len(logs), "crypto": core.crypto.available,
            "semantic_available": core.semantic_memory.available,
            "probe": probe, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, "rounds": logs}, open(out_path, "w", encoding="utf-8"),
            ensure_ascii=False, indent=1)  # 每轮增量写盘（断点续跑依赖）
        t = rec["timing_ms"]
        print(f"R{i:03d} Δ={rec['affinity_delta']:+g} base={rec['affinity_base']:g} "
              f"档={rec['affinity_stage']} 情绪={rec['emotion']} "
              f"总={t['total_ms']}ms 模型TTFB={t['llm_ttfb_ms']}ms "
              f"装配={t['assemble_plus_ms']}ms 字数={rec['assistant_len']} "
              f"用户：{text[:18]}", flush=True)
        if args.mode == "live":
            time.sleep(2.0)  # 降频防限流

    print(f"完成：{len(logs)} 轮 -> {out_path}")


if __name__ == "__main__":
    main()
