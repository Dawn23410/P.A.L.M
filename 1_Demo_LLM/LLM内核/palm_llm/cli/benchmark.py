# -*- coding: utf-8 -*-
"""项目统一基准测试（Benchmark）。

所有请求都走后端（backend/providers），复用全局 HTTP/2 客户端与 Provider 抽象，
不再自行实现 httpx 调用。仅输出「每项的最终结果」：通过与否 + 耗时/首字延迟/token 等指标，
不流式打印思维链、不倾倒全文。整合了原 test_api.py（维度矩阵 + 高级参数）与
test_think.py（深度思考项）与 bench_ttft.py（首字延迟测量）的功能。

用法:
  python benchmark.py                      # 跑维度矩阵（短/长 × 思考/不思考 × 流式/非流式）
  python benchmark.py --list               # 列出测试项（不联网）
  python benchmark.py --provider bigmodel --model glm-4.6v
  python benchmark.py --no-stream          # 全部强制非流式
  python benchmark.py --adv                # 矩阵 + 高级 API 参数随机测试
  python benchmark.py --adv-only           # 只跑高级参数测试
  python benchmark.py --cases 5,6          # 只跑第 5、6 项（也可写名称子串，如 "深度思考"）
  python benchmark.py --no-pause           # 测试完直接退出（双击运行时默认会暂停等回车防闪退）

凭证优先级：config.json 中的提供方 → 环境变量 BIGMODEL_API_KEY → 兜底常量（建议改用环境变量）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from typing import Optional


from ..server.config import load_config, get_provider
from ..server.models import Message, ModelParameters, ProviderConfig
from palm_llm.providers import get_provider_instance
from palm_llm.providers.base import close_client


# ============================ 默认配置 ============================
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.6v"
# 兜底凭证（沿用 test_api.py 的常量）；建议改用环境变量 BIGMODEL_API_KEY 避免明文落盘。
DEFAULT_API_KEY = "替换为你的Key或设置环境变量BIGMODEL_API_KEY"

_THINKING_HINTS = ("4.6", "4.5", "z1", "think", "reasoning")
_STD_PARAMS = {"temperature", "top_p", "max_tokens", "frequency_penalty", "presence_penalty"}


# ============================ 工具函数 ============================
def supports_thinking(model: str) -> bool:
    n = (model or "").lower()
    return any(h in n for h in _THINKING_HINTS)


def mask_key(k: str) -> str:
    if not k:
        return "(空)"
    if len(k) <= 8:
        return "*" * len(k)
    return k[:4] + "*" * (len(k) - 8) + k[-4:]


def _is_json(text: str) -> bool:
    if not text or not text.strip():
        return False
    try:
        json.loads(text.strip())
        return True
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            json.loads(m.group(0))
            return True
        except Exception:
            return False
    return False


def _tok(usage: dict, key: str) -> int:
    return (usage or {}).get(key) or 0


def _reasoning_tokens(usage: dict) -> int:
    det = (usage or {}).get("completion_tokens_details") or {}
    if isinstance(det, dict):
        return det.get("reasoning_tokens", 0) or 0
    return 0


# ============================ 测试矩阵（2×2×2） ============================
# 短句作对照，长句做压测（多约束/多步骤）；每项只用一次。
BENCH_CASES = [
    {"name": "短句·不思考·流式",   "length": "短句", "think": False, "stream": True,
     "prompt": "用一句话介绍你自己。"},
    {"name": "短句·不思考·非流式", "length": "短句", "think": False, "stream": False,
     "prompt": "用一句话回答：今天天气怎么样？"},
    {"name": "短句·深度思考·流式", "length": "短句", "think": True,  "stream": True,
     "prompt": "用一句话概括：为什么天空是蓝色的？"},
    {"name": "短句·深度思考·非流式", "length": "短句", "think": True, "stream": False,
     "prompt": "1 到 100 的所有奇数之和是多少？只给出最终数字。"},
    {"name": "长句·不思考·流式",   "length": "长句", "think": False, "stream": True,
     "prompt": "请写一篇关于『蜜蜂如何分工协作维持整个蜂群运转』的科普短文，面向小学高年级读者。"
               "要求：① 文章总长度不少于 600 字；② 分成『侦察与招募』『内勤与哺育』『守卫与清洁』"
               "三个小节，每节带小标题；③ 语言通俗、尽量不使用专业术语，必要时用生活比喻解释；"
               "④ 结尾用一句话总结蜂群协作给人类的启示。请直接开始写正文，不要任何前言、客套或"
               "『以下是文章』之类的引导语，写满后再自然收尾。"},
    {"name": "长句·不思考·非流式", "length": "长句", "think": False, "stream": False,
     "prompt": "请逐步推理并完整解答下面这道工程问题：甲、乙两人合作完成一项工程，甲单独做 12 天可完成，"
               "乙单独做 18 天可完成。两人先合作 4 天后，甲因事离开，剩余工程由乙独自完成。"
               "第一问：乙还需要多少天才能做完？第二问：若乙的工作效率因疲劳每天下降 10%（即第 n 天"
               "只完成原效率的 0.9 的 n-1 次方），则乙还需多少天（结果近似到小数点后两位）？"
               "第三问：若在合作阶段再加入丙（丙单独做 9 天可完成），三人合作前 4 天，之后甲、丙离开，"
               "剩余由乙独自完成，乙还需几天？请对每一问写出设元、列方程、求解、验算的全过程，"
               "并在最后用一句话总结三问答案。"},
    {"name": "长句·深度思考·流式", "length": "长句", "think": True,  "stream": True,
     "prompt": "请深入思考并详细阐述：『人工智能会不会取代程序员？』要求从以下五个角度系统展开："
               "① 技术可行性——当前大模型在代码生成、调试、重构上的真实能力与仍存在的边界；"
               "② 经济成本——企业用人成本与 AI 调用成本随团队规模变化的权衡；"
               "③ 协作模式——AI 作为结对编程伙伴如何改变需求拆解、评审与上线的流程；"
               "④ 历史类比——以计算器、编译器、低代码平台的出现类比，说明每次『替代恐慌』后的真实演化；"
               "⑤ 5 年内现实边界——哪些岗位会被显著压缩、哪些能力反而会增值。请先给出你的核心判断，"
               "再逐点论证，篇幅 800 字以上，结尾给一句面向应届程序员的建议。"},
    {"name": "长句·深度思考·非流式", "length": "长句", "think": True, "stream": False,
     "prompt": "请深度推理并完整解答：① 解方程 x² - 5x + 6 = 0，写出因式分解法与求根公式法两种解法；"
               "② 求该抛物线与直线的 y = 2x + 1 的交点坐标，并说明交点在几何上的意义；"
               "③ 将直线改为 y = kx + 1，讨论参数 k 变化时（分 k < -1、-1 < k < 1、k > 1 三种情形）"
               "交点个数的判定条件，并给出对应的判别式推导；④ 若把二次函数推广为 y = ax² + bx + c（a≠0），"
               "请给出一般情形下它与任意直线 y = mx + n 交点个数的通用判定公式。要求每一步推理严密、"
               "关键结论加粗标注，并在文末对第 ④ 问结论做一组具体数值验证。"},
]


# ============================ 高级 API 参数随机测试 ============================
# 每项用随机生成的合法值；check(reply, usage, value) 返回 False/抛异常 → 未通过。
ADV_TESTS = [
    {"name": "temperature（采样温度）", "param": "temperature",
     "gen": lambda: round(random.uniform(0.0, 2.0), 2), "prompt": "用一句话描述『海』。"},
    {"name": "top_p（核采样）", "param": "top_p",
     "gen": lambda: round(random.uniform(0.1, 1.0), 2), "prompt": "用一句话描述『山』。"},
    {"name": "max_tokens（最大生成长度）", "param": "max_tokens",
     "gen": lambda: random.choice([16, 32, 64, 128]), "prompt": "写一段关于秋天的长文。",
     "check": lambda r, u, v: _tok(u, "completion_tokens") <= v + 8},
    {"name": "presence_penalty（存在惩罚）", "param": "presence_penalty",
     "gen": lambda: round(random.uniform(-2.0, 2.0), 2), "prompt": "用『苹果』开头写一句话。"},
    {"name": "frequency_penalty（频率惩罚）", "param": "frequency_penalty",
     "gen": lambda: round(random.uniform(-2.0, 2.0), 2), "prompt": "写一首包含『风』字的短诗。"},
    {"name": "stop（停止词）", "param": "stop",
     "gen": lambda: random.choice(["。", "###", "\n"]), "prompt": "讲一个关于猫的短故事。",
     "check": lambda r, u, v: v not in r},
    {"name": "seed（随机种子）", "param": "seed",
     "gen": lambda: random.randint(1, 9999), "prompt": "用一句话写一句格言。"},
    {"name": "n（多候选返回）", "param": "n",
     "gen": lambda: random.choice([1, 2]), "prompt": "给一款新产品起一个名字。",
     "no_stream": True},  # OpenAI 规范不允许 stream + n>1
    {"name": "response_format（JSON 模式）", "param": "response_format",
     "gen": lambda: {"type": "json_object"},
     "prompt": "返回一个 JSON，包含字段 name(字符串) 和 age(数字)。只输出 JSON。",
     "check": lambda r, u, v: _is_json(r)},
]


# ============================ 提供方解析 ============================
def resolve_provider(args) -> tuple[ProviderConfig, Optional[str]]:
    """按优先级解析提供方配置：--provider > config 中自动识别的 BigModel > 激活提供方 > 兜底默认。"""
    cfg = load_config()
    if args.provider:
        pc = get_provider(args.provider)
        if pc:
            return pc, None
        # 配置里没有，但用户显式指定 → 用兜底 base_url 建一个最小配置
        return ProviderConfig(id=args.provider, name=args.provider, type="openai_compat",
                              base_url=DEFAULT_BASE_URL,
                              api_key=os.getenv("BIGMODEL_API_KEY", "")), "显式指定(配置缺失)"
    for p in cfg.providers:
        blob = f"{(p.base_url or '')} {(p.id or '')} {(p.name or '')}".lower()
        if "bigmodel" in blob:
            return p, None
    ap = get_provider()
    if ap:
        return ap, None
    key = os.getenv("BIGMODEL_API_KEY") or DEFAULT_API_KEY
    return ProviderConfig(id="bigmodel", name="BigModel(兜底)", type="openai_compat",
                          base_url=DEFAULT_BASE_URL, api_key=key), "兜底默认凭证"


# ============================ 核心：通过后端跑一项 ============================
async def _run_one(provider, model: str, prompt: str, params: ModelParameters, stream: bool) -> dict:
    """复用后端 provider.complete() 跑一次请求，返回聚合指标（不打印正文/思维链）。"""
    t0 = time.time()
    ttft = None
    chunks: list[str] = []
    usage: dict = {}
    err = ""
    try:
        async for ev in provider.complete([Message(role="user", content=prompt)],
                                          params, model, stream=stream):
            if "content" in ev and ev["content"]:
                if ttft is None:
                    ttft = time.time() - t0
                chunks.append(ev["content"])
            elif ev.get("done"):
                usage = ev.get("usage") or {}
        reply = "".join(chunks)
        ok = bool(reply.strip())
    except Exception as e:
        reply = ""
        ok = False
        err = f"{type(e).__name__}: {e}"
        usage = {}
    return {
        "reply": reply, "elapsed": time.time() - t0, "ttft": ttft,
        "usage": usage, "ok": ok, "err": err,
    }


def _build_params(overrides: dict) -> ModelParameters:
    params = ModelParameters()
    params.max_tokens = 8192   # 默认开到模型输出上限，避免深度思考正文被截断；高级测试里的 max_tokens 项会显式覆盖
    extra: dict = {}
    for k, v in overrides.items():
        if k in _STD_PARAMS:
            setattr(params, k, v)
        else:
            extra[k] = v
    if extra:
        params.extra_body = extra
    return params


# ============================ 跑矩阵 ============================
async def run_matrix(provider, model: str, cases: list, force_no_stream: bool):
    rows: list[dict] = []
    passed = 0
    print(f"\n[维度矩阵] 共 {len(cases)} 项")
    for i, c in enumerate(cases, 1):
        params = ModelParameters()
        params.max_tokens = 8192   # 开到模型输出上限：深度思考长答案需充足预算，否则正文被思维链挤占截断为空
        if supports_thinking(model):
            params.extra_body = {"thinking": {"type": "enabled" if c["think"] else "disabled"}}
        stream = c["stream"] and not force_no_stream
        res = await _run_one(provider, model, c["prompt"], params, stream)
        if res["ok"]:
            passed += 1
        ttft_s = f"{res['ttft']:.2f}s" if res["ttft"] is not None else "—"
        if res["ok"]:
            status = "✓"
        else:
            status = f"✗ {res['err'][:36]}"
        ctok = _tok(res["usage"], "completion_tokens")
        rtok = _reasoning_tokens(res["usage"])
        print(f"[{i}/{len(cases)}] {c['name']:<20} {status}  耗时 {res['elapsed']:.2f}s  "
              f"首字 {ttft_s}  生成 {ctok}  思考 {rtok}")
        rows.append({"name": c["name"], "elapsed": res["elapsed"], "ttft": res["ttft"],
                     "ctok": ctok, "rtok": rtok, "ok": res["ok"]})
    return passed, len(cases), rows


# ============================ 跑高级参数 ============================
async def run_adv(provider, model: str, force_no_stream: bool):
    rng = random.Random()
    rows: list[dict] = []
    passed = 0
    print(f"\n[高级 API 参数随机测试] 共 {len(ADV_TESTS)} 项")
    for case in ADV_TESTS:
        overrides = case["gen"]()
        params = _build_params(overrides)
        stream = (not case.get("no_stream", False)) and not force_no_stream
        res = await _run_one(provider, model, case["prompt"], params, stream)
        ok = res["ok"]
        note = ""
        if case.get("check"):
            try:
                if case["check"](res["reply"], res["usage"], overrides) is False:
                    ok = False
                    note = "（参数校验未过）"
            except Exception as e:
                ok = False
                note = f"（校验异常:{e}）"
        if ok:
            passed += 1
        status = "✓" if ok else f"✗ {res['err'][:30]}"
        nsf = "  (强制非流式)" if case.get("no_stream") else ""
        print(f"  {case['name']:<26} {status}  {case['param']}={overrides!r}  "
              f"耗时 {res['elapsed']:.2f}s{note}{nsf}")
        rows.append({"name": case["name"], "param": case["param"], "value": overrides,
                     "time": res["elapsed"], "ok": ok})
    return passed, len(ADV_TESTS), rows


# ============================ 总结 ============================
def _print_summary(model, m_rows, a_rows, m_pass, m_total, a_pass, a_total) -> None:
    print("\n" + "=" * 60)
    print(f"[总结] 模型 {model}")
    if m_total:
        stream_ttfts = [r["ttft"] for r in m_rows if r["ttft"] is not None]
        avg_ttft = sum(stream_ttfts) / len(stream_ttfts) if stream_ttfts else 0.0
        avg_el = sum(r["elapsed"] for r in m_rows) / max(len(m_rows), 1)
        tot_c = sum(r["ctok"] for r in m_rows)
        tot_r = sum(r["rtok"] for r in m_rows)
        print(f"  矩阵   通过 {m_pass}/{m_total}  ·  平均耗时 {avg_el:.2f}s  ·  "
              f"流式平均首字 {avg_ttft:.2f}s  ·  总生成 {tot_c}  ·  总思考 {tot_r}")
    if a_total:
        avg_a = sum(r["time"] for r in a_rows) / max(len(a_rows), 1)
        print(f"  高级参数 通过 {a_pass}/{a_total}  ·  平均耗时 {avg_a:.2f}s")
    overall = (m_pass + a_pass, m_total + a_total)
    verdict = "✓ 全部通过" if overall[0] == overall[1] and overall[1] else "✗ 存在未通过项"
    print(f"  总体  通过 {overall[0]}/{overall[1]}  ·  {verdict}")
    print("=" * 60)


# ============================ 用例筛选 / 列出 ============================
def _select_cases(spec: Optional[str]) -> list:
    if not spec:
        return BENCH_CASES
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(BENCH_CASES):
                out.append(BENCH_CASES[idx])
        else:
            for c in BENCH_CASES:
                if part in c["name"]:
                    out.append(c)
    return out or BENCH_CASES


def _list_cases() -> None:
    print("维度矩阵（2×2×2 = 8 项）：")
    for i, c in enumerate(BENCH_CASES, 1):
        print(f"  {i}. {c['name']}  (长度={c['length']} 思考={'是' if c['think'] else '否'} "
              f"传输={'流式' if c['stream'] else '非流式'})")
    print("\n高级 API 参数随机测试：")
    for c in ADV_TESTS:
        print(f"  - {c['name']}")


# ============================ 双击防闪退 ============================
def _should_pause() -> bool:
    if not sys.stdout.isatty():
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32  # type: ignore[attr-defined]
        count = k.GetConsoleProcessList(None, 0)
        return count <= 1  # 双击独占控制台
    except Exception:
        return True


# ============================ 主流程 ============================
async def _run_all(provider, model: str, args, note: Optional[str], pc: ProviderConfig) -> None:
    print("=" * 60)
    print(f"项目基准测试 (Benchmark)   模型 {model}")
    print(f"提供方 {pc.name}   凭证 {mask_key(pc.api_key)}{('  [' + note + ']') if note else ''}")
    print("=" * 60)

    m_pass = m_total = a_pass = a_total = 0
    m_rows = a_rows = []
    if not args.adv_only:
        cases = _select_cases(args.cases)
        m_pass, m_total, m_rows = await run_matrix(provider, model, cases, args.no_stream)
    if args.adv or args.adv_only:
        a_pass, a_total, a_rows = await run_adv(provider, model, args.no_stream)

    _print_summary(model, m_rows, a_rows, m_pass, m_total, a_pass, a_total)
    await close_client()


def main() -> None:
    p = argparse.ArgumentParser(description="项目统一基准测试（复用后端发起真实请求）")
    p.add_argument("--provider", default=None, help="提供方 id（默认自动识别 BigModel / 激活提供方）")
    p.add_argument("--model", default=None, help="模型名（默认 glm-4.6v）")
    p.add_argument("--no-stream", action="store_true", help="全部强制非流式")
    p.add_argument("--adv", action="store_true", help="矩阵 + 高级 API 参数随机测试")
    p.add_argument("--adv-only", action="store_true", help="只跑高级参数测试")
    p.add_argument("--cases", default=None, help="只跑指定项：逗号分隔序号(如 5,6)或名称子串(如 深度思考)")
    p.add_argument("--list", action="store_true", help="列出测试项（不联网）")
    p.add_argument("--no-pause", action="store_true",
                   help="测试完直接退出（默认双击控制台下会暂停等回车，防止一闪而过）")
    args = p.parse_args()

    if args.list:
        _list_cases()
        return

    pc, note = resolve_provider(args)
    if not pc.api_key:
        pc.api_key = os.getenv("BIGMODEL_API_KEY") or DEFAULT_API_KEY
    if not pc.api_key or pc.api_key.startswith("替换为"):
        print("✗ 未找到 API Key：请在 config.json 填写，或设置环境变量 BIGMODEL_API_KEY。")
        return

    model = args.model or DEFAULT_MODEL
    provider = get_provider_instance(pc)
    try:
        asyncio.run(_run_all(provider, model, args, note, pc))
    except KeyboardInterrupt:
        print("\n已中断。")
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        if not args.no_pause and _should_pause():
            try:
                input("\n按回车键关闭窗口…")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    main()
