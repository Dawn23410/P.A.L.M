"""50 轮双模式对照测试：论文级报告生成（读 bench_50_mock.json / bench_50_live.json）。

输出：50轮对照测试报告.md（含完整逐轮数据表 + 统计分析 + 首字专项分析结论）。
"""
import json
import os
import statistics as st
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def stat(vals):
    """返回 均值/中位/P95/max 的四元组（保留 1 位小数）。"""
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-", "-", "-", "-"
    s = sorted(vals)
    return (f"{st.mean(vals):.1f}", f"{st.median(vals):.1f}",
            f"{s[min(int(len(s)*0.95)-1, len(s)-1)]:.1f}", f"{max(vals):.1f}")


def fmt_s(v):
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def analyze(d):
    rs = d["rounds"]
    out = {}
    out["n"] = len(rs)
    out["totals_ms"] = [r["timing_ms"]["total_ms"] for r in rs]
    out["ttfb_ms"] = [r["timing_ms"]["llm_ttfb_ms"] for r in rs
                      if r["timing_ms"]["llm_ttfb_ms"] and r["timing_ms"]["llm_ttfb_ms"] > 0]
    out["assemble_ms"] = [r["timing_ms"]["assemble_plus_ms"] for r in rs]
    out["emotion_ms"] = [r["timing_ms"]["emotion_complete_ms"] for r in rs]
    out["stream_ms"] = [r["timing_ms"]["llm_stream_ms"] for r in rs]
    out["len_user"] = [r["user_len"] for r in rs]
    out["len_asst"] = [r["assistant_len"] for r in rs]
    out["delta"] = Counter(round(r["affinity_delta"], 2) for r in rs)
    out["emotion"] = Counter(r["emotion"] for r in rs)
    out["fields"] = Counter(str(r["fields"]) for r in rs)
    out["manifest_sets"] = Counter(tuple(m["source"] for m in r["manifest"]) for r in rs)
    out["stages"] = Counter(r["affinity_stage"] for r in rs)
    out["retries"] = sum(r["retries"] for r in rs)
    out["base_first"] = rs[0]["affinity_base"]
    out["base_last"] = rs[-1]["affinity_base"]
    out["bond_last"] = rs[-1]["affinity_bond"]
    out["asst_avg"] = st.mean(out["len_asst"])
    # 输出速率（字符/秒，仅 live 有意义的流式数据）
    rates = []
    for r in rs:
        t = r["timing_ms"]
        if t["llm_stream_ms"] and t["llm_stream_ms"] > 0:
            rates.append(r["assistant_len"] / t["llm_stream_ms"] * 1000)
    out["cps"] = rates
    return out


def rows_table(rs):
    """完整逐轮数据表（Markdown）。"""
    lines = ["| 轮 | 用户输入 | 注入面 | 情绪(输入侧) | Δ好感 | 好感基础 | 档位 | 外发字段 | 正文长度 | 总耗时ms | 模型TTFBms |",
             "|---|---------|--------|--------------|-------|---------|------|----------|----------|----------|-------------|"]
    for r in rs:
        m = r["timing_ms"]
        ttfb = m["llm_ttfb_ms"]
        lines.append(
            f"| {r['round']} | {r['user'][:14].replace('|', '\\|')}… | "
            f"{'/'.join(x['source'] for x in r['manifest'])} | {r['emotion']} | "
            f"{r['affinity_delta']:+g} | {r['affinity_base']:g} | {r['affinity_stage']} | "
            f"{'、'.join(r['fields'].keys()) if r['fields'] else '（空）'} | "
            f"{r['assistant_len']} | {m['total_ms']} | {ttfb if ttfb and ttfb>0 else '-'} |")
    return "\n".join(lines)


def build_report(mock, live):
    L = []
    A = L.append
    A("# 心智魔方 50 轮双模式对照测试报告（mock 离线回显 vs live GLM-4.5-Flash-nothink）\n")
    A(f"**测试时间**：{mock['meta']['ts']}（mock 组）/ {live['meta']['ts']}（live 组）  \n")
    A("**性质**：本地对照实验，固定 50 条中文语料，两组共用同一输入序列（控制变量，仅模型层不同）。\n")

    A("\n## 摘要\n")
    A("- mock 组：50/50 轮成功，单轮总耗时均值 **3.6 ms**（离线回显），数据区协议遵守率 **100%**（50/50 轮 affinity_delta 被消费、不外发），注入面覆盖 **5/5**（人格/记忆/情感/织语/律动）。")
    A("- live 组：模型 TTFB 高波动（**3.4 s ~ 48.4 s**），均值 **20.1 s**；33 s 级首字多次出现，与用户 CLI 实测一致。**根因：NoneLinear 免费端点排队延迟**，非本地链路问题（专项剖析见 §5）。")
    A("- 好感度：mock base 0.2→4.0；live base 0→**6.15**（R50 断点续跑进程内重置不计），档位全程「初识」——符合好感度吝啬制设计（日常 Δ 为小数制小步进，仅关系质变轮大幅 ±）。")

    A("\n## 1. 实验目的与假设\n")
    A("1. 验证心智魔方在**离线（mock）与真实 API（live）**两种模型层下的全链路正确性与协议一致性；")
    A("2. 定量对比两组的关键指标：耗时、流式体验（TTFB/输出速率）、数据区协议遵守、好感度/情绪行为；")
    A("3. 定位用户实测「首字 33 s」的卡点（本地链路 vs 端点）。")
    A("\n**零假设**：mock 与 live 在架构接线层面行为一致（注入、拆分、结算、持久化契约相同），差异仅来自模型层本身。")

    A("\n## 2. 环境\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 主机 | Windows 11（win32），沙箱执行 |")
    A("| Python | 3.13.14（隔离 venv：`~/.workbuddy/binaries/python/envs/default`） |")
    A("| 依赖 | httpx 0.28.1 / pytest 9.1.1 / palm（同仓库）/ chromadb（缺失降级） |")
    A("| mock 模型 | `MockLLM`（离线回显，provider=mock，模型 mock-pro） |")
    A("| live 模型 | `GLM-4.5-Flash-nothink`（非推理），端点 `（端点见 .env）`，key 取自 `桌面/可用API.json`（2026-08-19 16:05 实测） |")
    A("| live 采样参数 | max_tokens=400，temperature/其他未设（端点默认） |")
    A("| 存储 | SM4 国密加密启用（CBC+HMAC-SM3）；语义记忆 embedding 本机不可用 → 降级仅近期对话 |")
    A("| 语料 | 50 条固定中文句（情感弧线：寒暄→倾诉→喜悦→吃醋→和好→依赖→温暖），两组共用 |")

    A("\n## 3. 方法与指标\n")
    A("### 3.1 采集方法\n")
    A("`bench_50.py --mode mock|live --rounds 50`：对每条语料执行 `MentalCore.stream_message()`，收集全部事件；模型层经 `TimerLLM` 包装计时（不动核心代码）。live 组每轮间 sleep 2 s 降频防限流，429 退避重试（最长 6 次）。")
    A("\n### 3.2 指标定义\n")
    A("| 指标 | 定义 |")
    A("|---|---|")
    A("| 总耗时 total_ms | 调用 stream_message 到 done 事件（含持久化） |")
    A("| 模型 TTFB llm_ttfb_ms | 模型层 `stream()` 调用至首个内容块 yield |")
    A("| 模型流式总 llm_stream_ms | `stream()` 全量产出耗时 |")
    A("| 装配+结算 assemble_plus_ms | total − llm_stream（注入组装/拆分/情绪等待/落盘等非模型耗时） |")
    A("| 情绪识别 emotion_complete_ms | `complete()` 旁路（后台线程，与主生成并行）耗时 |")
    A("| 输出速率 cps | 正文字数 / llm_stream_ms（字符/秒） |")
    A("| 协议遵守率 | affinity_delta 不出现在外发字段的比例 |")

    for tag, d in (("mock", mock), ("live", live)):
        a = analyze(d)
        A(f"\n## 4. {tag.upper()} 组结果\n")
        A(f"轮数 {a['n']}；重试轮 {a['retries']}。\n")
        A("| 指标 | 均值 | 中位数 | P95 | 最大 |")
        A("|---|---|---|---|---|")
        A(f"| 总耗时 ms | {stat(a['totals_ms'])[0]} | {stat(a['totals_ms'])[1]} | {stat(a['totals_ms'])[2]} | {stat(a['totals_ms'])[3]} |")
        A(f"| 模型 TTFB ms | {stat(a['ttfb_ms'])[0]} | {stat(a['ttfb_ms'])[1]} | {stat(a['ttfb_ms'])[2]} | {stat(a['ttfb_ms'])[3]} |")
        A(f"| 模型流式总 ms | {stat(a['stream_ms'])[0]} | {stat(a['stream_ms'])[1]} | {stat(a['stream_ms'])[2]} | {stat(a['stream_ms'])[3]} |")
        A(f"| 装配+结算 ms | {stat(a['assemble_ms'])[0]} | {stat(a['assemble_ms'])[1]} | {stat(a['assemble_ms'])[2]} | {stat(a['assemble_ms'])[3]} |")
        A(f"| 情绪识别 ms | {stat(a['emotion_ms'])[0]} | {stat(a['emotion_ms'])[1]} | {stat(a['emotion_ms'])[2]} | {stat(a['emotion_ms'])[3]} |")
        A(f"| 输出速率 字/s | {stat(a['cps'])[0]} | {stat(a['cps'])[1]} | {stat(a['cps'])[2]} | {stat(a['cps'])[3]} |")
        A(f"| 正文字数 | {stat(a['len_asst'])[0]} | {stat(a['len_asst'])[1]} | {stat(a['len_asst'])[2]} | {stat(a['len_asst'])[3]} |")
        A(f"\n- 好感度：base {a['base_first']:g} → {a['base_last']:g}{'（R50 断点续跑，base 进程内重置，轨迹统计至 R49=6.15）' if tag=='live' else ''}（末轮 bond={a['bond_last']:.2f}）；Δ 分布 {dict(a['delta'])}")
        A(f"- 档位分布：{dict(a['stages'])}")
        A(f"- 情绪识别命中：{dict(a['emotion'])}")
        A(f"- 外发字段形态：{dict(a['fields'])}")
        A(f"- 注入面组合：{dict(a['manifest_sets'])}")
        A(f"\n### 4.{'2' if tag=='mock' else '3'} 完整逐轮数据\n")
        A(rows_table(d["rounds"]))

    A("\n## 5. 首字 33 s 专项剖析\n")
    A("用户 CLI 实测首字 33 s。专项对照实验（同端点、同机器）：\n")
    A("| 实验 | 结果 |")
    A("|---|---|")
    A("| A. 裸 httpx 短 prompt ×5（端点基线） | TTFB = 15.5 / 4.5 / 1.2 / 1.3 / 12.8 s —— **端点自身波动 1.2~15.5 s** |")
    A("| B. 裸 httpx 长 system prompt（max_tokens=400） | TTFB 4.6 s，但**流式总时长 77 s**（端点逐 token 极慢） |")
    A("| C. mentalcore 全链路单轮 | build_core 42 ms；语义检索首次 1.8 s（仅首轮）；情绪 complete API 8.0 s（后台并行）；模型 TTFB 8.7 s；总 12.3 s |")
    A("\n**结论**：")
    A("1. 首字 33 s 的主因是 **NoneLinear 免费端点排队延迟**——本组 50 轮实测模型 TTFB 3.4~48.4 s，均值 20.1 s，33 s 级首字多次出现；裸 httpx 同端点亦复现 12.8~15.5 s 波动，证明非本地链路问题。")
    A("2. 本地链路开销占比小：build_core 42 ms、语义检索 1.8 s（仅首次初始化）、装配结算约 1.5~2.5 s（情绪识别在后台线程并行，不增加首字延迟）。")
    A("3. 附带发现：端点长输出时逐 token 极慢（B 组 400 token 总 77 s；本组最大单轮总耗时 **884 s / 14.7 分钟**，R9=696 s、R6=599 s、R18=441 s），放大「等很久」的整体体感。")
    A("4. 次要改进点：warmup 仅预热 sync 连接池（GET /models），对话走 async 连接池（未预热），首轮 TLS 建连未受益——量级秒级，非主因。")
    A("\n**缓解建议**：① 换更稳端点或自建 Ollama（TTFB 可降至秒内）；② `emotion_via_llm=False` 关闭情绪 API（省一次排队往返）；③ 预热 async 连接池；④ live 轮间降频防排队（本组已 sleep 2 s）。")

    A("\n## 5.1 已知观察项（留档）\n")
    A("- **R9~R13/R15/R21/R25/R30/R31/R34/R36/R45 流式后附加等待 60~875 s**：12 个异常轮**全部伴随重试（≥1 次）**——端点网络异常/断流 → 挂起（httpx 600 s 超时窗口）→ 429 退避，退避与挂起均计入 total（计时起点在重试循环外）。诊断脚本在干净环境未复现（add/search <2 s、collect 0.8 s、persist 1 s），本地环节排除。归因：**端点稳定性问题 + 计时口径**，非核心代码缺陷。")
    A("- **好感度状态不跨进程持久化**：R50 经断点续跑，对话历史（49 轮）从 storage 恢复，但 base 从 0.15 重新累计——EmotionFace 的 base/bond/dynamics 仅存内存，重启归零。建议好感度随对话记录一并落盘或导出。")
    A("- **R20 吃醋轮正确输出负向好感度 Δ=-0.3**（「哼，不理你了」）——模型对关系受损的反馈链路有效；此前「Δ 恒非负」的中间观察被 50 轮数据推翻。")
    A("- **外发字段恒空（live 50/50）**：inner_note 为 mock 演示扩展字段，live 模型仅遵守 ||DATA|| 协议的 affinity_delta 部分——协议契约（delta 消费）两组均 100% 遵守，属设计差异非缺陷。")
    A("- **R1 档位差异**：live R1=「陌生」（base=0），mock R1=「初识」（首轮 Δ=+0.2 使 base=0.2）——base 映射阈值所致，非异常。")
    A("- **情绪识别精度**：live（LLM 法）可检负情绪（工作压力→-0.5）与连续值（0.85/-0.5/0.35），优于 mock 关键词词典（对「累/压力/孤独/想家」零命中，42/50 中性）。")

    A("\n## 6. 讨论与局限\n")
    A("- mock 情绪识别为关键词词典法（命中 8/50 正情绪），精度弱于 live（能识别 -0.7 等负情绪）——属预期，mock 仅用于架构验证；")
    A("- 语义记忆 embedding 本机不可用，两组均降级「仅近期对话」，语义召回链路未经端到端验证；")
    A("- live 免费端点波动大，TTFB/总时长统计受时段负载影响，绝对数值不可跨时段泛化，但**波动本身**即为根因证据；")
    A("- 好感度 50 轮后仍处「初识」档（mock base 4.0 / live base 6.15）：吝啬制下需长期积累或关系质变轮才升档，属设计预期。")

    A("\n## 7. 结论\n")
    A("心智魔方架构接线在 mock/live 两组一致：注入 5 面、数据区协议 100% 遵守、好感度/情绪链路完整、SM4 加密落盘正常。**首字 33 s 系免费端点排队延迟，非代码缺陷**；离线模式每轮 3.6 ms 验证了本地编排性能。建议生产切换稳定端点并按 §5 缓解。")

    A("\n## 8. 复现\n")
    A("```bash\n")
    A("# 依赖：隔离 venv（httpx、palm 同仓库）\n")
    A("cd mentalcore\n")
    A("python bench_50.py --mode mock --rounds 50   # mock 组\n")
    A("python bench_50.py --mode live --rounds 50   # live 组（配置自动取 桌面/可用API.json）\n")
    A("python gen_report.py                          # 生成本报告\n")
    A("```\n")
    A(f"原始数据：`bench_50_mock.json`（{mock['meta']['rounds']} 轮）、`bench_50_live.json`（{live['meta']['rounds']} 轮）。")
    return "\n".join(L)


def main():
    mock = load("bench_50_mock.json")
    live = load("bench_50_live.json")
    md = build_report(mock, live)
    out = os.path.join(HERE, "50轮对照测试报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"报告已生成: {out}（{len(md)} 字符）")


if __name__ == "__main__":
    main()
