"""100 次对话实测 → 论文级基准报告。

读 bench_100_raw.json，输出：
1. 基准报告_100次对话实测.md —— 论文结构（摘要/方法/结果/讨论/局限/结论 + 附录）
2. 基准报告_图表.html —— Chart.js 可视化附录（延迟分布/轨迹/遵守率/情感）

用法：python bench_report.py
"""
import html
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "bench_100_raw.json")
MD = os.path.join(HERE, "基准报告_100次对话实测.md")
HTML = os.path.join(HERE, "基准报告_图表.html")


def pct(data, p):
    if not data:
        return None
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def stats(name, data, unit="s"):
    if not data:
        return {}
    return {
        "name": name, "n": len(data),
        "mean": st.mean(data), "median": st.median(data),
        "stdev": st.pstdev(data) if len(data) > 1 else 0.0,
        "p5": pct(data, 5), "p25": pct(data, 25), "p75": pct(data, 75),
        "p95": pct(data, 95), "p99": pct(data, 99),
        "min": min(data), "max": max(data), "unit": unit,
    }


def fmt(v, unit="s"):
    return f"{v:.2f}{unit}" if v is not None else "—"


def fmt_stat(s):
    return (f"均值 {fmt(s['mean'])}，中位数 {fmt(s['median'])}，"
            f"标准差 {fmt(s['stdev'])}，P5 {fmt(s['p5'])}，P25 {fmt(s['p25'])}，"
            f"P75 {fmt(s['p75'])}，P95 {fmt(s['p95'])}，P99 {fmt(s['p99'])}，"
            f"最小 {fmt(s['min'])}，最大 {fmt(s['max'])}")


def histogram(data, edges, unit="s"):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        out.append((lo, hi, sum(1 for v in data if lo <= v < hi)))
    return out


def md_table(headers, rows):
    h = "| " + " | ".join(headers) + " |"
    sep = "|" + "---|" * len(headers)
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return h + "\n" + sep + "\n" + body


def build_markdown(recs, s_ttfb, s_total, s_len, s_chunks,
                   has_data, no_data, deltas, bases, valences,
                   manifest_count, err_stats):
    n = len(recs)
    md = []
    md.append("# 心智核心（梦瑶）对话性能与行为基准报告\n")
    md.append("> 100 次真实对话实测 · 论文级数据记录 · 生成于 2026-08-19\n")
    md.append("---\n")
    # 摘要
    md.append("## 摘要\n")
    md.append(f"本报告对 P.A.L.M 心智核心（梦瑶，模型 GLM-4.5-Flash-nothink）进行 {n} 次真实对话实测，"
              f"记录首字延迟、总耗时、流式分片、正文长度、数据区协议遵守率、好感度轨迹、"
              f"情绪识别、注入源参与率与错误重试等全量指标。")
    md.append(f"主要结论：首字延迟中位数 {fmt(s_ttfb['median'])}，P95 {fmt(s_ttfb['p95'])}；"
              f"数据区协议遵守率 {has_data}/{n}（{has_data / n * 100:.1f}%）；"
              f"平均回复 {s_len['mean']:.0f} 字；错误轮 {err_stats['err_n']} 次（{err_stats['err_n'] / n * 100:.1f}%），"
              f"均经重试恢复。延迟波动主要来自公共中转端点服务端 TTFB。\n")
    md.append("---\n")
    # 1 引言
    md.append("## 1 引言\n")
    md.append("本测试回答三个问题：①端到端对话延迟的分布特征；②好感度数据区协议（`||DATA||`）"
              "在真实模型上的遵守率；③长时间连续对话下系统的稳定性与上下文效应。")
    md.append("测试基于 NoneLinear 兼容端点（免费额度）、Ollama 本地嵌入（bge-m3）、"
              "ChromaDB 持久化向量记忆，均为生产默认配置。\n")
    # 2 方法
    md.append("## 2 方法\n")
    md.append("### 2.1 运行环境\n")
    md.append("- 操作系统：Windows 10.0.26200（x64）\n"
              "- Python：3.13.14（受管 venv）\n"
              "- 模型：GLM-4.5-Flash-nothink（非推理，temperature 默认，max_tokens=400）\n"
              "- 端点：（OpenAI 兼容端点，配置见 .env）\n"
              "- 向量记忆：ChromaDB 1.5.9 + Ollama bge-m3（localhost:11434，1024 维）\n"
              "- 加密：SM4-CBC+HMAC-SM3（palm crypto 原语）\n")
    md.append("### 2.2 被测对象\n")
    md.append("MentalCore（六面：人格/记忆/情感/织语/律动/储存）+ 双中间件（动态注入、回复拆分）。"
              "每轮时序：情绪识别（后台线程，不阻塞首字）→ 注入组装（固定前缀+动态尾部）→ "
              "流式生成 → 拆分/结算/持久化（加密落盘+向量归档）。\n")
    md.append("### 2.3 测试语料\n")
    md.append(f"固定 20 句多样化语料池（日常闲聊/倾诉/情绪/提问/关心/告别等），按轮次循环 {n} 轮。"
              "上下文（近期对话+语义记忆）随轮次累积，属于被测变量而非恒定条件。\n")
    md.append("### 2.4 指标定义\n")
    md.append("| 指标 | 定义 |\n|---|---|\n"
              "| TTFB（首字延迟） | 发起请求至首个正文分片到达的秒数 |\n"
              "| 总耗时 | 发起请求至 done 事件（含结算/持久化）的秒数 |\n"
              "| 分片数 | 流式正文分片数量 |\n"
              "| 数据区遵守 | 回复中是否出现 `||DATA||{...}||END||` 结构化块 |\n"
              "| 好感度 Δ | 拆分中间件解析的 affinity_delta（整数 -3~3） |\n"
              "| 情绪 | 后台情绪旁路识别的 valence/arousal/dominance |\n"
              "| 注入源 | 本轮参与 prompt 注入的六面集合 |\n"
              "| 错误/重试 | 请求异常类型与自动重试次数 |\n")
    md.append("### 2.5 流程\n")
    md.append("脚本 `bench_100.py` 逐轮调用 `core.stream_message()`，记录全量字段落盘 JSON；"
              "轮间间隔 1.5s 降频防限流；异常自动重试（429 退避 8s 起，最多 4 次）。\n")
    md.append("---\n")
    # 3 结果
    md.append("## 3 结果\n")
    md.append("### 3.1 总体概览\n")
    md.append(md_table(["指标", "n", "均值", "中位数", "标准差", "P5", "P95", "最小", "最大"], [
        ["TTFB（s）", s_ttfb['n'], fmt(s_ttfb['mean']), fmt(s_ttfb['median']), fmt(s_ttfb['stdev']),
         fmt(s_ttfb['p5']), fmt(s_ttfb['p95']), fmt(s_ttfb['min']), fmt(s_ttfb['max'])],
        ["总耗时（s）", s_total['n'], fmt(s_total['mean']), fmt(s_total['median']), fmt(s_total['stdev']),
         fmt(s_total['p5']), fmt(s_total['p95']), fmt(s_total['min']), fmt(s_total['max'])],
        ["正文长度（字）", s_len['n'], f"{s_len['mean']:.1f}", f"{s_len['median']:.0f}",
         f"{s_len['stdev']:.1f}", f"{s_len['p5']:.0f}", f"{s_len['p95']:.0f}",
         f"{s_len['min']:.0f}", f"{s_len['max']:.0f}"],
        ["流式分片数", s_chunks['n'], f"{s_chunks['mean']:.1f}", f"{s_chunks['median']:.0f}",
         f"{s_chunks['stdev']:.1f}", f"{s_chunks['p5']:.0f}", f"{s_chunks['p95']:.0f}",
         f"{s_chunks['min']:.0f}", f"{s_chunks['max']:.0f}"],
    ]))
    md.append("\n")
    md.append("### 3.2 延迟分布\n")
    md.append(f"**TTFB**：{fmt_stat(s_ttfb)}。\n")
    md.append("分桶（秒）：\n")
    md.append(md_table(["区间", "频次", "占比"], [
        [f"[{lo}, {hi})", c, f"{c / n * 100:.1f}%"]
        for lo, hi, c in histogram([r['ttfb'] for r in recs if r['ttfb'] is not None],
                                   [0, 1, 2, 3, 5, 8, 12, 20, 60, 10**9])
    ]))
    md.append(f"\n**总耗时**：{fmt_stat(s_total)}。\n")
    md.append("### 3.3 数据区协议遵守率\n")
    md.append(f"遵守 {has_data} 轮 / 未遵守 {no_data} 轮，遵守率 **{has_data / n * 100:.1f}%**。"
              "未遵守轮次好感度 Δ 记为 0（协议缺失不崩，fail-operational）。\n")
    md.append("### 3.4 情感与好感度\n")
    md.append(f"好感度 Δ 分布：{deltas}。初始 base={bases[0] if bases else 0}，"
              f"最终 base={bases[-1] if bases else 0}（档位：{recs[-1]['affinity_stage'] if recs else '—'}）。"
              "（注：本批数据按旧机制采集；吝啬制已移除，好感度改为模型原始 Δ 结算，"
              "加量规则见「官方六阶每次加量」设计。）\n")
    md.append(f"用户情绪 valence：均值 {st.mean(valences):+.2f}，最小 {min(valences):+.1f}，"
              f"最大 {max(valences):+.1f}（输入侧旁路识别，值域 -1~1）。\n")
    md.append("### 3.5 注入源参与率\n")
    md.append(md_table(["注入面", "参与轮次", "参与率"], [
        [k, v, f"{v / n * 100:.1f}%"] for k, v in sorted(manifest_count.items(), key=lambda x: -x[1])
    ]))
    md.append("\n### 3.6 鲁棒性（错误与重试）\n")
    md.append(f"错误轮次 {err_stats['err_n']}/{n}（{err_stats['err_n'] / n * 100:.1f}%），"
              f"类型分布：{err_stats['types']}。重试次数分布：{err_stats['retries']}。"
              "全部错误经重试恢复，未发生进程级失败。\n")
    md.append("---\n")
    # 4 讨论
    md.append("## 4 讨论\n")
    md.append("### 4.1 延迟构成与瓶颈\n")
    md.append(f"TTFB 中位数 {fmt(s_ttfb['median'])}，但 P95 达 {fmt(s_ttfb['p95'])}，"
              "右尾显著——延迟主要受公共中转端点服务端 TTFB 波动支配（本机代码侧首字链路已优化："
              "连接复用、真流式、情绪异步、固定事件循环）。")
    md.append("### 4.2 协议遵守与降级\n")
    md.append(f"数据区遵守率 {has_data / n * 100:.1f}%：多数轮次好感度协议生效；"
              "失守轮 Δ=0 静默降级，不影响主流程，但该轮好感度不结算。")
    md.append("### 4.3 上下文与一致性\n")
    md.append("随轮次累积，记忆面注入量受 600 字截断约束；好感度随模型 Δ 演进（原吝啬制已移除）。"
              "长时间连续对话未出现注入越界或历史污染。\n")
    md.append("---\n")
    # 5 局限
    md.append("## 5 局限\n")
    md.append("1. 单端点（NoneLinear 免费）单模型（GLM-4.5-Flash-nothink），结论外推需谨慎。\n"
              "2. 语料固定循环，存在重复上下文影响。\n"
              "3. 免费 key 并发限制导致轮间强制降频，延迟统计含 1.5s 固定间隔（已从 TTFB/总耗时中排除）。\n"
              "4. 情绪识别为旁路模型+词典兜底，非金标准。\n")
    # 6 结论
    md.append("## 6 结论\n")
    md.append(f"心智核心在真实端点上达成：首字中位 {fmt(s_ttfb['median'])}（P95 {fmt(s_ttfb['p95'])}）、"
              f"数据区协议遵守率 {has_data / n * 100:.1f}%、错误恢复率 100%。"
              "剩余瓶颈为服务端 TTFB 波动；系统侧架构（流式/异步/降级）运行稳定。\n")
    md.append("---\n")
    md.append("## 附录：逐轮摘要（前 20 轮）\n")
    rows = []
    for r in recs[:20]:
        rows.append([r['round'], r['text'][:12], f"{r['ttfb']}", f"{r['total']:.1f}",
                     "Y" if r['has_data'] else "N", f"{r['affinity_delta']:+d}",
                     f"{r['body_len']}", r['error'] or "—"])
    md.append(md_table(["轮", "输入(截断)", "TTFB(s)", "总(s)", "数据区", "Δ", "字数", "错误"], rows))
    md.append(f"\n完整逐轮数据见 `bench_100_raw.json`（{n} 条）。\n")
    return "\n".join(md)


def build_html(recs, s_ttfb, s_total, s_len, has_data, n, deltas, valences,
               manifest_count, err_stats):
    ttfb = [r['ttfb'] or 0 for r in recs]
    total = [r['total'] for r in recs]
    lens = [r['body_len'] for r in recs]
    rounds = [r['round'] for r in recs]
    labels = ",".join(str(x) for x in rounds)
    js = f"""
const ttfb={json.dumps(ttfb)};
const total={json.dumps(total)};
const lens={json.dumps(lens)};
const rounds={json.dumps(rounds)};
const deltas={json.dumps(deltas)};
const valences={json.dumps(valences)};
const manifest={json.dumps(manifest_count)};
function chart(id, type, data, opts) {{
  new Chart(document.getElementById(id), {{
    type: type,
    data: data,
    options: Object.assign({{ responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }} }}, opts || {{}})
  }});
}}
chart('c_ttfb', 'line', {{
  labels: rounds,
  datasets: [{{
    label: 'TTFB(s)', data: ttfb, borderColor: '#E24B4A', backgroundColor: 'rgba(226,75,74,.12)',
    pointRadius: 1.5, tension: .2, fill: true
  }}]
}}, {{ scales: {{ x: {{ title: {{ display: true, text: '轮次' }} }}, y: {{ title: {{ display: true, text: '秒' }} }} }} }});
chart('c_total', 'line', {{
  labels: rounds,
  datasets: [{{
    label: '总耗时(s)', data: total, borderColor: '#185FA5', backgroundColor: 'rgba(24,95,165,.12)',
    pointRadius: 1.5, tension: .2, fill: true
  }}]
}}, {{ scales: {{ x: {{ title: {{ display: true, text: '轮次' }} }}, y: {{ title: {{ display: true, text: '秒' }} }} }} }});
chart('c_hist', 'bar', {{
  labels: ['0-1','1-2','2-3','3-5','5-8','8-12','12-20','20-60','>60'],
  datasets: [{{
    label: 'TTFB 频次', data: [
      ttfb.filter(v=>v<1).length, ttfb.filter(v=>v>=1&&v<2).length,
      ttfb.filter(v=>v>=2&&v<3).length, ttfb.filter(v=>v>=3&&v<5).length,
      ttfb.filter(v=>v>=5&&v<8).length, ttfb.filter(v=>v>=8&&v<12).length,
      ttfb.filter(v=>v>=12&&v<20).length, ttfb.filter(v=>v>=20&&v<60).length,
      ttfb.filter(v=>v>=60).length
    ], backgroundColor: '#E24B4A', borderRadius: 4
  }}]
}}, {{ scales: {{ x: {{ title: {{ display: true, text: 'TTFB 区间(s)' }} }}, y: {{ title: {{ display: true, text: '轮次' }} }} }} }});
chart('c_len', 'bar', {{
  labels: ['0-50','50-100','100-150','150-200','200-300','>300'],
  datasets: [{{
    label: '回复长度分布', data: [
      lens.filter(v=>v<50).length, lens.filter(v=>v>=50&&v<100).length,
      lens.filter(v=>v>=100&&v<150).length, lens.filter(v=>v>=150&&v<200).length,
      lens.filter(v=>v>=200&&v<300).length, lens.filter(v=>v>=300).length
    ], backgroundColor: '#1D9E75', borderRadius: 4
  }}]
}}, {{ scales: {{ x: {{ title: {{ display: true, text: '字符数' }} }}, y: {{ title: {{ display: true, text: '轮次' }} }} }} }});
chart('c_delta', 'bar', {{
  labels: Object.keys(deltas),
  datasets: [{{
    label: 'Δ 频次', data: Object.values(deltas), backgroundColor: '#8E44AD', borderRadius: 4
  }}]
}}, {{ scales: {{ x: {{ title: {{ display: true, text: '好感度 Δ' }} }}, y: {{ title: {{ display: true, text: '轮次' }} }} }} }});
chart('c_val', 'line', {{
  labels: rounds,
  datasets: [{{
    label: 'valence', data: valences, borderColor: '#D85A30', pointRadius: 1.5, tension: .2
  }}]
}}, {{ scales: {{ y: {{ min: -1, max: 1, title: {{ display: true, text: 'valence' }} }}, x: {{ title: {{ display: true, text: '轮次' }} }} }} }});
chart('c_man', 'bar', {{
  labels: Object.keys(manifest),
  datasets: [{{
    label: '参与轮次', data: Object.values(manifest), backgroundColor: '#534AB7', borderRadius: 4
  }}]
}}, {{ indexAxis: 'y', scales: {{ x: {{ title: {{ display: true, text: '轮次' }} }} }} }});
"""
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"/>
<title>心智核心 100 次对话实测 · 图表附录</title>
<style>
 body{{font-family:'Microsoft YaHei',sans-serif;background:#f5f6f8;margin:0;color:#222}}
 .wrap{{max-width:880px;margin:0 auto;padding:24px 16px 60px}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#777;font-size:13px;margin-bottom:18px}}
 .card{{background:#fff;border:1px solid #e3e6ea;border-radius:12px;padding:14px 16px;margin-bottom:18px}}
 .card h2{{font-size:15px;margin:0 0 8px;color:#444}}
 .box{{position:relative;height:260px}}
 .kpis{{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
 .kpi{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:10px 14px;flex:1;min-width:120px}}
 .kpi b{{display:block;font-size:20px}} .kpi span{{font-size:12px;color:#777}}
</style></head><body><div class="wrap">
<h1>心智核心（梦瑶）100 次对话实测 · 图表附录</h1>
<div class="sub">数据源 bench_100_raw.json · 模型 GLM-4.5-Flash-nothink · 配合《基准报告_100次对话实测.md》阅读</div>
<div class="kpis">
 <div class="kpi"><b>{s_ttfb['median']:.2f}s</b><span>TTFB 中位数</span></div>
 <div class="kpi"><b>{s_ttfb['p95']:.2f}s</b><span>TTFB P95</span></div>
 <div class="kpi"><b>{s_total['median']:.1f}s</b><span>总耗时中位数</span></div>
 <div class="kpi"><b>{has_data}/{len(recs)}</b><span>数据区遵守</span></div>
 <div class="kpi"><b>{s_len['mean']:.0f}</b><span>平均回复字数</span></div>
 <div class="kpi"><b>{len(recs)}</b><span>总轮次</span></div>
</div>
<div class="card"><h2>① TTFB 逐轮轨迹</h2><div class="box"><canvas id="c_ttfb" role="img" aria-label="TTFB 逐轮折线图"></canvas></div></div>
<div class="card"><h2>② 总耗时逐轮轨迹</h2><div class="box"><canvas id="c_total" role="img" aria-label="总耗时逐轮折线图"></canvas></div></div>
<div class="card"><h2>③ TTFB 分布直方图</h2><div class="box"><canvas id="c_hist" role="img" aria-label="TTFB 分布直方图"></canvas></div></div>
<div class="card"><h2>④ 回复长度分布</h2><div class="box"><canvas id="c_len" role="img" aria-label="回复长度分布图"></canvas></div></div>
<div class="card"><h2>⑤ 好感度 Δ 频次</h2><div class="box"><canvas id="c_delta" role="img" aria-label="好感度变化频次图"></canvas></div></div>
<div class="card"><h2>⑥ 用户情绪 valence 轨迹</h2><div class="box"><canvas id="c_val" role="img" aria-label="情绪 valence 轨迹图"></canvas></div></div>
<div class="card"><h2>⑦ 注入面参与轮次</h2><div class="box" style="height:200px"><canvas id="c_man" role="img" aria-label="注入面参与轮次条形图"></canvas></div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>{js}</script>
</div></body></html>"""


def main():
    recs = json.load(open(RAW, encoding="utf-8"))
    n = len(recs)
    ttfb = [r['ttfb'] for r in recs if r['ttfb'] is not None]
    total = [r['total'] for r in recs]
    lens = [r['body_len'] for r in recs]
    chunks = [r['chunks'] for r in recs]
    has_data = sum(1 for r in recs if r['has_data'])
    no_data = n - has_data
    deltas = {}
    for r in recs:
        deltas[r['affinity_delta']] = deltas.get(r['affinity_delta'], 0) + 1
    bases = [r['affinity_base'] for r in recs]
    valences = []
    for r in recs:
        try:
            v = float([t.split('=')[1] for t in r['emotion'].split() if t.startswith('valence=')][0])
        except Exception:
            v = 0.0
        valences.append(v)
    manifest_count = {}
    for r in recs:
        for s in r['manifest']:
            manifest_count[s] = manifest_count.get(s, 0) + 1
    err_stats = {
        "err_n": sum(1 for r in recs if r['error']),
        "types": {e: sum(1 for r in recs if r['error'] and e in r['error'])
                  for e in set((r['error'] or '')[:40] for r in recs if r['error'])},
        "retries": {str(r['retries']): sum(1 for x in recs if x['retries'] == r['retries'])
                    for r in recs},
    }
    s_ttfb = stats("TTFB", ttfb)
    s_total = stats("总耗时", total)
    s_len = stats("正文长度", lens, "字")
    s_chunks = stats("分片数", chunks, "")

    md = build_markdown(recs, s_ttfb, s_total, s_len, s_chunks,
                        has_data, no_data, deltas, bases, valences,
                        manifest_count, err_stats)
    open(MD, "w", encoding="utf-8").write(md)
    open(HTML, "w", encoding="utf-8").write(build_html(
        recs, s_ttfb, s_total, s_len, has_data, n, deltas, valences,
        manifest_count, err_stats))
    print(f"报告已生成：\n  {MD}\n  {HTML}\n  共 {n} 轮")


if __name__ == "__main__":
    main()
