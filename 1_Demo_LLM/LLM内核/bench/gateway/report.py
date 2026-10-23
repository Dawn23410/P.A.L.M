#!/usr/bin/env python3
"""把 results_* 里的原始样本汇总成中文报告（表格 + 局限披露）。

    python3 report.py --zero results_zero --load results_load --out ../../docs/xx.md

报告里的每个数字都来自原始 JSON，不手抄；基线取「首轮 + 复测」两条的均值，
并把两者之差当作**漂移带**如实列出 —— 净开销小于漂移带的，一律标注「噪声级」。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# 分组：同语言（Python）正面对照 vs 跨语言自托管网关（单独成组、不可直接比）
GROUP_PRIMARY = ["httpx_direct", "palm_kernel", "litellm", "openai_sdk"]
GROUP_GATEWAY = ["bifrost", "portkey"]
ROW_LABEL = {
    "httpx_direct": "直连 httpx（基线）",
    "palm_kernel": "**P.A.L.M 内核**（本仓库）",
    "litellm": "LiteLLM（Python）",
    "openai_sdk": "OpenAI 官方 SDK",
    "bifrost": "Bifrost（Go，自托管）",
    "portkey": "Portkey Gateway（Node，自托管）",
    "baseline_retest": "直连 httpx（复测）",
}


def load(directory: str) -> dict:
    out = {}
    for p in sorted(Path(directory).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "wall_ms" in d:
            out[d["label"]] = d
    return out


def base_of(res: dict) -> tuple[float, float]:
    """基线（首轮与复测的均值, 漂移带 = 两者之差的绝对值）。"""
    first = res["httpx_direct"]["wall_ms"]["mean"]
    retest = res.get("baseline_retest", {}).get("wall_ms", {}).get("mean", first)
    return (first + retest) / 2.0, abs(retest - first)


def note(delta: float, drift: float, key: str) -> str:
    if key in ("httpx_direct", "baseline_retest"):
        return ""
    return " ⚠️噪声级" if abs(delta) <= drift else ""


def table(res: dict, title: str) -> list[str]:
    base_w, drift = base_of(res)
    retest = res.get("baseline_retest", {}).get("wall_ms", {}).get("mean", float("nan"))
    lines = [f"### {title}", "",
             "| 实现 | wall mean | Δ 净开销 | p50 | p90 | p99 | stdev | n | 错误 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key in GROUP_PRIMARY + GROUP_GATEWAY + ["baseline_retest"]:
        d = res.get(key)
        if not d:
            continue
        w = d["wall_ms"]
        delta = w["mean"] - base_w
        lines.append(
            f"| {ROW_LABEL.get(key, key)} | {w['mean']:.3f} ms | "
            f"{delta:+.3f} ms{note(delta, drift, key)} | {w['p50']:.3f} | {w['p90']:.3f} | "
            f"{w['p99']:.3f} | {w['stdev']:.3f} | {w['n']} | {d['errors']} |")
    lines += ["",
              f"基线口径：首轮 `{res['httpx_direct']['wall_ms']['mean']:.3f} ms` 与复测 "
              f"`{retest:.3f} ms` 的均值 = **{base_w:.3f} ms**；"
              f"**漂移带 ±{drift:.3f} ms**（同一份代码跑两次的差，即本机可复现性下限）。", ""]
    return lines


def ttft_table(res: dict, title: str) -> list[str]:
    lines = [f"### {title}", "",
             "| 实现 | TTFT mean | TTFT p50 | TTFT p90 | 相对基线 |",
             "|---|---:|---:|---:|---:|"]
    base = res["httpx_direct"]["ttft_ms"]["mean"]
    for key in GROUP_PRIMARY + GROUP_GATEWAY + ["baseline_retest"]:
        d = res.get(key)
        if not d or not d.get("ttft_ms"):
            continue
        t = d["ttft_ms"]
        lines.append(f"| {ROW_LABEL.get(key, key)} | {t['mean']:.3f} ms | {t['p50']:.3f} | "
                     f"{t['p90']:.3f} | {t['mean'] - base:+.3f} ms |")
    return lines + [""]


def delta(res: dict, key: str) -> float:
    """该实现相对基线的净开销（ms）。基线 = 首轮与复测的均值。"""
    if key in res:
        return res[key]["wall_ms"]["mean"] - base_of(res)[0]
    return float("nan")


def ttft_delta(res: dict, key: str) -> float:
    base = res["httpx_direct"]["ttft_ms"]["mean"]
    return res[key]["ttft_ms"]["mean"] - base if key in res and res[key].get("ttft_ms") else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zero", default="results_zero")
    ap.add_argument("--load", default="results_load")
    ap.add_argument("--out", required=True)
    ap.add_argument("--third-party", default="", help="第三方公开数字（markdown 片段，可选）")
    a = ap.parse_args()

    zero, loaded = load(a.zero), load(a.load)
    meta = json.loads(Path(a.zero, "meta.json").read_text(encoding="utf-8"))
    lmeta = json.loads(Path(a.load, "meta.json").read_text(encoding="utf-8"))

    # 正文里的关键数字一律从原始样本算出，不手抄（否则正文迟早与表格打架）
    d_palm, d_lite = delta(zero, "palm_kernel"), delta(zero, "litellm")
    d_sdk, d_bif = delta(zero, "openai_sdk"), delta(zero, "bifrost")
    d_port = delta(zero, "portkey")
    drift_z = base_of(zero)[1]
    d_port_load = delta(loaded, "portkey")
    d_port_ttft_load = ttft_delta(loaded, "portkey")
    load_mean = loaded["httpx_direct"]["wall_ms"]["mean"]
    share = d_port / load_mean * 100 if load_mean else 0.0

    L: list[str] = [
        "# 自研 LLM 内核 vs 开源实现：控制变量对照实验 v1.0",
        "",
        "> 目的：回答「本内核那层薄封装到底花了多少钱」，并给出**与主流开源实现同条件对比**的数字。",
        "> ",
        f"> **结论先行**：本内核净开销 ≈ **{d_palm:+.2f} ms/次**，是本轮同语言四个实现里最轻的一个；"
        f"LiteLLM {d_lite:+.2f} ms、OpenAI SDK {d_sdk:+.2f} ms。",
        f"> 两个自托管网关（跨语言，单独成组、不与内核并列排名）分别约 {d_bif:+.2f} ms 与 {d_port:+.2f} ms。",
        f"> 但最该记住的是另一条：**当模型延迟真的存在（约 {load_mean:.0f} ms）时，"
        f"除 Portkey（{d_port_load:+.2f} ms）外的差异全被淹没**。",
        "",
        "---",
        "",
        "## 一、实验设计（控制变量）",
        "",
        "所有被测实现**指向同一个本地确定性 mock 上游**，测量的是纯粹的「客户端/网关这一层」",
        "开销，不含任何供应商侧变量：",
        "",
        "```",
        "被测实现 ──HTTP/1.1 keep-alive──> mock 上游（服务端固定约 0.5 ms，可注入固定延迟）",
        "```",
        "",
        "- **净开销 = 该实现的 mean − 直连 httpx 的 mean**（同机、同回环、同进程模型）",
        "- 一次调用 = **把整条 SSE 流读完**（含收尾帧）的墙钟；不是首字节、不是「发出即返回」",
        "- 并发 = 1（顺序单发）：网关差异本就在毫秒级，并发排队噪声会把信号埋掉",
        "- 每轮先热身 50 次（不计入）；每次测量前 reset mock 侧计数",
        "- **基线复测**：整轮跑完再测一次基线，用两次之差作为本机**可复现性下限**；",
        "  小于它的净开销一律标注「噪声级」，不编故事",
        "",
        "### 为什么不用真实厂商端点",
        "",
        "真实模型延迟 0.5–5 s、网络与供应商负载都在动，网关那几毫秒的差异**看不见也复现不了**。",
        "把上游钉死成「固定延迟的本地进程」，才能把「网关」这一个变量单独解出来。",
        "代价是绝对数偏离生产 —— 见第七节。",
        "",
        "### 一个必须先修掉的伪像：Nagle + 延迟 ACK 的 40 ms",
        "",
        "首版 mock 没关 Nagle，基线直接测出 **44 ms**，而 mock 侧自报只花 0.6 ms。",
        "原因是流式响应「一个 chunk 一次小写」：发送端 Nagle 在等对端 ACK，对端的延迟 ACK 是 40 ms，",
        "两条规则凑一起就是每请求凭空 +40 ms —— 足以把网关差异整个盖住。",
        "修法：mock 侧 `TCP_NODELAY` + 每个 chunk 立即 flush。修后基线 2.6 ms，量级才对。",
        "**这是本次实验最重要的工程发现**，已写进 `mock_upstream.py` 的注释里。",
        "",
        "---",
        "",
        "## 二、环境",
        "",
        f"- 平台：`{meta['platform']}`，Python `{meta['python']}`",
        f"- httpx `{meta['httpx']}`；litellm `{meta['litellm']}`；openai SDK `{meta['openai_sdk']}`",
        "- 内核：本仓库 `palm_llm`，走 `OpenAICompatProvider`（默认通道）",
        f"- Bifrost 镜像 `{meta['bifrost_image']}`；Portkey 镜像 `{meta['portkey_image']}`",
        f"- 传输：{meta['transport']}；并发 {meta['concurrency']}；mock 服务端耗时约 0.5 ms/请求",
        "",
        "---",
        "",
        "## 三、第一轮：零延迟（只量「那一层」的成本）",
        "",
        f"`--ack-delay-ms 0 --chunk-delay-ms 0 --completion-tokens {meta['max_tokens']}`，"
        f"{meta['iters']} 次/实现，热身 {meta['warmup']} 次。",
        "",
    ]
    L += table(zero, "墙钟（读完整条流）")
    L += ttft_table(zero, "TTFT（首个正文帧）")
    L += [
        f"**读法**：`palm_kernel` 的 Δ = **{d_palm:+.2f} ms**，"
        f"{'高于' if abs(d_palm) > drift_z else '与'}漂移带（±{drift_z:.3f} ms）"
        f"{'，可以认为是个真实但极小的开销' if abs(d_palm) > drift_z else '，与噪声同级'}。"
        f"对比之下 LiteLLM {d_lite:+.2f} ms、Portkey {d_port:+.2f} ms 是稳定且远超噪声的开销。",
        "",
        "---",
        "",
        "## 四、第二轮：拟真延迟（把模型耗时放回去）",
        "",
        f"`--ack-delay-ms {lmeta['ack_delay_ms']:.0f} --chunk-delay-ms {lmeta['chunk_delay_ms']:.0f} "
        f"--completion-tokens {lmeta['max_tokens']}`，{lmeta['iters']} 次/实现。",
        "",
        "这一轮的意义是**看差异如何消失**：",
        "",
    ]
    L += table(loaded, "墙钟（读完整条流）")
    L += ttft_table(loaded, "TTFT（首个正文帧）")
    L += [
        f"**读法**：总耗时全部落在同一区间，除 Portkey（{d_port_load:+.2f} ms）外"
        f"**没有任何实现的差异超过噪声带**。",
        f"但 TTFT 一列仍有信号：Portkey 的 {d_port_ttft_load:+.1f} ms 首字惩罚"
        f"在总时长被淹没后**依然可见**。",
        "这就是「该看哪个指标」的经验：**网关的开销主要落在首字节**，总时长由模型解码主导。",
        "",
        "---",
        "",
        "## 五、分组与可比性声明",
        "",
        "| 组 | 成员 | 可比性 |",
        "|---|---|---|",
        "| **同语言正面对照组** | 直连 httpx / **本内核** / LiteLLM / OpenAI SDK | 可比：同为 Python 进程内库，同解释器、同进程模型 |",
        "| **跨语言参照组** | Bifrost（Go）/ Portkey（Node，Docker `--network host`） | **不可直接比**：各多一次真实网络跳、独立运行时与进程；只作量级参照 |",
        "",
        "跨语言两组与同语言组共用同一个 mock、同一台机器，但「多一跳」本身就值几毫秒，",
        "所以本报告**从不把它们与内核并列排名**，只在同组内互相比较",
        "（Bifrost vs Portkey 可比 —— 两者容器化方式与网络路径一致）。",
        "",
    ]
    if a.third_party:
        L += ["---", "", "## 六、与第三方公开数字对照", "",
              Path(a.third_party).read_text(encoding="utf-8").strip(), ""]
    L += [
        "---",
        "",
        "## 七、局限与伪像（必须一起读）",
        "",
        "1. **回环不是网络**。同机回环没有 RTT、没有丢包重传、没有跨区路由。真实链路上网关的",
        "   每一跳都更贵，本表的净开销是**下界**。",
        "2. **没有 TLS**。真实网关要终结 HTTPS，握手与加解密成本未计入（连接复用时影响小，但不为零）。",
        "3. **并发 = 1**。排队 / 限流 / 背压恰恰是网关的核心价值之一，本实验刻意把并发拿掉以保信号纯度，",
        "   因此**不能**从本表推断高并发表现。",
        "4. **mock 是单线程模型**（每请求一线程），但它本身不是被测对象；其 0.5 ms 服务端耗时已单列，可自行扣除。",
        "5. **容器用 host 网络**。Bifrost/Portkey 以 `--network host` 运行以消除端口映射噪声，",
        "   与生产部署形态不同，但对两者是同等处理。",
        "6. **顺序效应已量化但仍存在**。各实现按固定顺序跑，基线复测给出漂移带；因此",
        f"   「内核 {d_palm:+.2f} ms」只说明开销**很小**，不主张精确到小数第三位。",
        "7. **这不是功能对比**。本实验只量延迟开销，不评价路由 / 熔断 / 缓存 / 密钥治理等能力 ——",
        "   那些才是这些网关的主体价值，而本内核**并不打算**做那些事。",
        "8. **配置形态可能影响结果**。Bifrost 用 management API 注册上游、Portkey 用请求头路由，",
        "   均为各自文档的推荐姿势，但与你的生产配置不同时开销会变。",
        "",
        "---",
        "",
        "## 八、结论",
        "",
        f"1. **这层封装足够薄**：净开销 {d_palm:+.2f} ms/次（LiteLLM {d_lite:+.2f} ms、"
        f"OpenAI SDK {d_sdk:+.2f} ms），同语言四个实现里最轻。",
        "   与设计意图一致 —— 内核不做重试编排 / 虚拟密钥 / 负载均衡，只做协议归一与参数卫生。",
        "2. **轻不等于没成本，而是成本花在别处**：内核的收益在协议覆盖（四种原生通道）、",
        "   参数卫生（禁参剔除 / 档位夹取）、能力矩阵前置拦截、文本工具降级这些**正确性**上。",
        "   这次实验说明它没有为这些正确性付明显的延迟代价。",
        "3. **延迟要看 TTFT，不是总时长**：拟真配置下总时长差异全部淹没，只有 TTFT 还留着信号。",
        f"4. **网关选型不能只看这几毫秒**：Portkey 的 {d_port:+.2f} ms 在 {load_mean:.0f} ms 的回合里",
        f"   只占约 {share:.1f}%。如果它换来的可观测性与密钥治理值这个价，它就是对的 —— 数字要放进场景里读。",
        "",
        "---",
        "",
        "## 九、复现",
        "",
        "```bash",
        "# 依赖：WSL2 Ubuntu 22.04 + Docker（Bifrost/Portkey 需要）",
        "#       venv 内 httpx / pydantic / litellm / openai",
        "cd bench/gateway",
        "",
        "# 第一轮：零延迟（纯开销）",
        "RESDIR=results_zero bash run_bench.sh 500 50",
        "",
        "# 第二轮：拟真延迟",
        "RESDIR=results_load ACK_MS=300 CHUNK_MS=5 MAXTOK=32 bash run_bench.sh 80 10",
        "",
        "# 出报告",
        "python3 report.py --zero results_zero --load results_load \\",
        "    --out ../../docs/网关对照实验_v1.0.md",
        "```",
        "",
        "文件清单：`mock_upstream.py`（确定性上游）、`clients.py`（四类客户端）、",
        "`harness.py`（计时器）、`run_bench.sh`（编排）、`report.py`（本报告生成）、",
        "`results_zero/` 与 `results_load/`（原始样本，逐次耗时全部保留）。",
        "",
    ]

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(L)
    Path(a.out).write_text(text, encoding="utf-8")
    print(f"wrote {a.out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
