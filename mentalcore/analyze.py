"""100 轮对话可视化分析：读 chat_100_log.json，生成自包含 HTML 报告（内联 SVG，无外部依赖）。

用法：
    python analyze.py               # 读默认日志，生成 chat_100_report.html
    python analyze.py --log xxx.json --out xxx.html
"""
import argparse
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# —— 档位区间（与 emotion.py OFFICIAL_6 对齐）——
STAGES = [("抵触", -50, -30), ("陌生", -30, 0), ("初识", 0, 20),
          ("友好", 20, 50), ("亲近", 50, 80), ("亲密", 80, 100)]
STAGE_BAND = [(name, lo, hi, "#c9d6e0") for name, lo, hi in STAGES]
SOURCES = ["persona", "memory", "emotion", "weave", "rhythm"]
SOURCE_CN = {"persona": "人格", "memory": "记忆", "emotion": "情感",
             "weave": "织语", "rhythm": "律动"}
SRC_COLOR = {"persona": "#e74c3c", "memory": "#2980b9", "emotion": "#8e44ad",
             "weave": "#27ae60", "rhythm": "#f39c12"}

PAD_L, PAD_R, PAD_T, PAD_B = 46, 14, 30, 28
W = 780


def svg_line(title, values, ymin, ymax, color="#c0392b", band=None,
             x_every=None, unit=""):
    H = 250
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = len(values)

    def X(i):
        return PAD_L + iw * (i / max(n - 1, 1))

    def Y(v):
        return PAD_T + ih * (1 - (v - ymin) / (ymax - ymin))

    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">']
    for g in range(6):
        v = ymin + (ymax - ymin) * g / 5
        y = Y(v)
        p.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="#ececec"/>')
        p.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#999">{v:g}</text>')
    if band:
        for label, lo, hi, color in band:
            y1, y2 = Y(hi), Y(lo)
            p.append(f'<rect x="{PAD_L}" y="{y1:.1f}" width="{iw:.0f}" height="{y2 - y1:.1f}" fill="{color}" opacity="0.30"/>')
            p.append(f'<text x="{PAD_L + 3}" y="{(y1 + y2) / 2 + 4:.1f}" font-size="9" fill="#7f8c8d">{label}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
    p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
    p.append(f'<circle cx="{X(n - 1):.1f}" cy="{Y(values[-1]):.1f}" r="3.5" fill="{color}"/>')
    step = x_every or max(1, n // 10)
    for i in range(0, n, step):
        p.append(f'<text x="{X(i):.1f}" y="{H - 8}" text-anchor="middle" font-size="10" fill="#999">{i + 1}</text>')
    p.append(f'<text x="{PAD_L}" y="{16}" font-size="13" font-weight="600" fill="#333">{html.escape(title)}{unit}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_multi_line(title, series, ymin, ymax, x_every=None):
    """series: list of (name, color, values)"""
    H = 250
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = max(len(v) for _, _, v in series)

    def X(i):
        return PAD_L + iw * (i / max(n - 1, 1))

    def Y(v):
        return PAD_T + ih * (1 - (v - ymin) / (ymax - ymin))

    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">']
    for g in range(6):
        v = ymin + (ymax - ymin) * g / 5
        y = Y(v)
        p.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="#ececec"/>')
        p.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#999">{v:g}</text>')
    for name, color, values in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
    step = x_every or max(1, n // 10)
    for i in range(0, n, step):
        p.append(f'<text x="{X(i):.1f}" y="{H - 8}" text-anchor="middle" font-size="10" fill="#999">{i + 1}</text>')
    legend = " ".join(
        f'<span style="color:{color};margin-right:14px">● {html.escape(name)}</span>'
        for name, color, _ in series)
    p.append(f'<text x="{PAD_L}" y="{16}" font-size="13" font-weight="600" fill="#333">{html.escape(title)}</text>')
    p.append(f'<text x="{PAD_L}" y="{H - 2}" font-size="11" fill="#555">{legend}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_bars(title, values, colors, ymin=0, x_every=None):
    """values: list of numbers；colors: 与值等长的颜色（涨红跌绿等）。"""
    H = 230
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = len(values)
    vmax = max(values + [1]) * 1.08 if ymin >= 0 else max(abs(v) for v in values + [1]) * 1.08

    def X(i):
        return PAD_L + iw * (i / max(n, 1))

    def Y(v):
        return PAD_T + ih * (1 - (v - ymin) / (vmax - ymin))

    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">']
    y0 = Y(0)
    p.append(f'<line x1="{PAD_L}" y1="{y0:.1f}" x2="{W - PAD_R}" y2="{y0:.1f}" stroke="#bbb"/>')
    bw = max(2.0, iw / n * 0.6)
    for i, v in enumerate(values):
        y = Y(v)
        h = abs(y - y0)
        top = min(y, y0)
        p.append(f'<rect x="{X(i) + iw / n * 0.2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(h, 0.5):.1f}" fill="{colors[i]}" opacity="0.85"/>')
    step = x_every or max(1, n // 10)
    for i in range(0, n, step):
        p.append(f'<text x="{X(i) + iw / n * 0.5:.1f}" y="{H - 8}" text-anchor="middle" font-size="10" fill="#999">{i + 1}</text>')
    p.append(f'<text x="{PAD_L}" y="{16}" font-size="13" font-weight="600" fill="#333">{html.escape(title)}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_heat(rows, n, x_every=None):
    """rows: list of (label, color, [0/1]*n)——注入源热力。"""
    cell = 6.4
    H = PAD_T + len(rows) * (cell + 10) + 18
    iw = n * cell
    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">']
    for r, (label, color, flags) in enumerate(rows):
        y = PAD_T + r * (cell + 10)
        p.append(f'<text x="{PAD_L - 6}" y="{y + cell - 2:.1f}" text-anchor="end" font-size="11" fill="#555">{html.escape(label)}</text>')
        for i, f in enumerate(flags):
            x = PAD_L + i * cell
            fill = color if f else "#f2f2f2"
            p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell - 1:.1f}" height="{cell - 1:.1f}" fill="{fill}" opacity="{"0.9" if f else "1"}"/>')
    step = x_every or max(1, n // 10)
    for i in range(0, n, step):
        p.append(f'<text x="{PAD_L + i * cell + cell / 2:.1f}" y="{H - 6}" text-anchor="middle" font-size="9" fill="#999">{i + 1}</text>')
    p.append(f'<text x="{PAD_L}" y="{14}" font-size="13" font-weight="600" fill="#333">每轮注入源热力（深色=该面参与本轮 prompt 注入）</text>')
    p.append("</svg>")
    return "".join(p)


def stage_of(base):
    for name, lo, hi in STAGES:
        if base <= hi:
            return name
    return STAGES[-1][0]


def build_report(logs, out_path):
    n = len(logs)
    base_vals = [r["affinity_base"] for r in logs]
    delta_vals = [r["affinity_delta"] for r in logs]
    dyn_vals = [r["affinity_dynamics"] for r in logs]
    valence = []
    for r in logs:
        e = r.get("emotion", "")
        v = 0.0
        try:
            for tok in e.split():
                if tok.startswith("valence="):
                    v = float(tok.split("=")[1])
        except Exception:
            pass
        valence.append(v)
    user_len = [len(r["user"]) for r in logs]
    asst_len = [r.get("assistant_len", len(r["assistant"])) for r in logs]

    # 注入源热力
    rows = []
    for src in SOURCES:
        flags = [1 if src in r.get("manifest", []) else 0 for r in logs]
        rows.append((SOURCE_CN[src], SRC_COLOR[src], flags))

    # KPI
    final_base = base_vals[-1] if base_vals else 0
    final_stage = logs[-1].get("affinity_stage") or stage_of(final_base) if logs else "?"
    sum_delta = sum(delta_vals)
    avg_delta = sum_delta / n if n else 0
    avg_valence = sum(valence) / n if n else 0
    avg_asst = sum(asst_len) / n if n else 0
    max_d = max(delta_vals) if delta_vals else 0
    min_d = min(delta_vals) if delta_vals else 0
    peak_idx = delta_vals.index(max_d) if delta_vals else -1

    # 关键轮次回放：首轮 / 峰值 / 低谷 / 尾轮
    pick = {0: "开场", n - 1: "收尾"}
    if peak_idx not in pick:
        pick[peak_idx] = f"好感峰值 Δ={max_d:+d}"
    low_idx = delta_vals.index(min_d) if delta_vals else -1
    if low_idx not in pick and low_idx >= 0:
        pick[low_idx] = f"好感低谷 Δ={min_d:+d}"
    replays = []
    for idx in sorted(pick):
        r = logs[idx]
        replays.append(
            f'<div class="turn"><div class="tag">{pick[idx]} · R{r["round"]}</div>'
            f'<div class="u"><b>阿杰：</b>{html.escape(r["user"])}</div>'
            f'<div class="m"><b>梦瑶：</b>{html.escape(r["assistant"])}</div>'
            f'<div class="meta">情绪 {r.get("emotion","")} · 好感度 {r["affinity_delta"]:+d}（累积 {r["affinity_base"]}）· 档位 {r.get("affinity_stage","")} · 注入 {",".join(r.get("manifest",[]))}</div>'
            f"</div>")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<title>梦瑶 × 阿杰 · 100 轮对话分析</title>
<style>
 body{{font-family:"Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#222}}
 .wrap{{max-width:860px;margin:0 auto;padding:24px 16px 60px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#777;font-size:13px;margin-bottom:18px}}
 .kpis{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px}}
 .kpi{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;min-width:130px;flex:1}}
 .kpi b{{display:block;font-size:22px}} .kpi span{{font-size:12px;color:#777}}
 .card{{background:#fff;border:1px solid #e3e6ea;border-radius:12px;padding:14px 16px;margin-bottom:18px}}
 .card h2{{font-size:15px;margin:0 0 8px;color:#444}}
 .turn{{border-left:3px solid #e74c3c;padding:8px 12px;margin:10px 0;background:#fafafa;border-radius:0 8px 8px 0}}
 .turn .tag{{font-size:11px;color:#e74c3c;font-weight:600;margin-bottom:4px}}
 .turn .u{{margin:2px 0}} .turn .m{{margin:2px 0;color:#333}}
 .turn .meta{{font-size:11px;color:#999;margin-top:4px}}
 .note{{font-size:12px;color:#888;margin-top:6px}}
</style>
</head>
<body><div class="wrap">
<h1>梦瑶 × 阿杰 · 100 轮对话分析</h1>
<div class="sub">真实对话驱动：用户侧发言由「用户扮演」模型基于梦瑶上一条回复动态生成 · 模型 GLM-4.5-Flash-nothink · 共 {n} 轮</div>

<div class="kpis">
 <div class="kpi"><b>{n}</b><span>对话轮数</span></div>
 <div class="kpi"><b>{final_base}</b><span>最终好感度（起始 0）</span></div>
 <div class="kpi"><b>{final_stage}</b><span>最终关系档位</span></div>
 <div class="kpi"><b>{sum_delta:+d}</b><span>好感度累计变化</span></div>
 <div class="kpi"><b>{avg_valence:+.2f}</b><span>平均用户情绪(valence)</span></div>
 <div class="kpi"><b>{avg_asst:.0f}</b><span>梦瑶平均回复字数</span></div>
</div>

<div class="card"><h2>① 关系好感度轨迹（含档位区间）</h2>
{svg_line("好感度 base", base_vals, -50, 100, "#c0392b", band=STAGE_BAND)}
<div class="note">色带为六档关系区间：抵触/陌生/初识/友好/亲近/亲密。⚠️ 本轮 100 轮数据按<strong>旧速率</strong>采集（模型每轮报 Δ=+2，约 40 轮封顶）；已修复为「吝啬制」——日常对话 Δ=0、仅关系质变轮 ±1（100 轮全加 ≈ 10 左右），修复从下次采集生效。</div>
</div>

<div class="card"><h2>② 每轮好感度变化 Δ（红=上升，绿=下降）</h2>
{svg_bars("好感度增量", delta_vals, ["#c0392b" if v >= 0 else "#27ae60" for v in delta_vals])}
</div>

<div class="card"><h2>③ 用户情绪三轴轨迹（valence 愉悦度 / arousal 激活度 / dominance 支配度）</h2>
{svg_multi_line("情绪轨迹", [("valence", "#e74c3c", valence), ("dynamics(心情)", "#8e44ad", dyn_vals)], -1, 1)}
</div>

<div class="card"><h2>④ 对话节奏（每轮字数）</h2>
{svg_multi_line("每轮字数", [("用户", "#3498db", user_len), ("梦瑶", "#e74c3c", asst_len)], 0, max(max(user_len + asst_len) * 1.15, 60))}
</div>

<div class="card"><h2>⑤ 注入源热力</h2>
{svg_heat(rows, n)}
<div class="note">深色格=该轮此面参与 prompt 注入。记忆面只在有历史后出现；情感面在 affinity_enabled 时始终注入。</div>
</div>

<div class="card"><h2>⑥ 关键轮次回放</h2>
{''.join(replays)}
</div>

</div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"报告已生成：{out_path}（{n} 轮）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(HERE, "chat_100_log.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "chat_100_report.html"))
    args = ap.parse_args()
    if not os.path.exists(args.log):
        print(f"日志不存在：{args.log}")
        return
    logs = json.load(open(args.log, encoding="utf-8"))
    build_report(logs, args.out)


if __name__ == "__main__":
    main()
