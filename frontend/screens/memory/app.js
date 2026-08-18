/* 记忆管理界面：检索 / 预算 / 情绪（契约端点：POST /api/memory/retrieve、GET /api/memory/status）。 */

import { post, get } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "记忆";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>记忆管理</h1>
    <div class="sub">语义检索 · Token 预算 · 情绪五因子（契约端点 POST /api/memory/retrieve）</div>
    <div class="panel">
      <div class="p-title">检索</div>
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <input class="txt" id="mem-query" style="flex:1" placeholder="输入查询…" />
        <button class="btn" id="mem-search">检索</button>
      </div>
      <div id="mem-result"><div class="sub">输入查询后检索记忆。</div></div>
    </div>`;

  const result = document.getElementById("mem-result");
  document.getElementById("mem-search").addEventListener("click", async () => {
    const q = document.getElementById("mem-query").value.trim();
    if (!q) return;
    result.innerHTML = `<div class="sub">检索中…</div>`;
    try {
      const j = await post("/api/memory/retrieve", { query: q, top_k: 5 });
      const items = j.results || j || [];
      if (!items.length) { result.innerHTML = `<div class="sub">无相关记忆。</div>`; return; }
      result.innerHTML = items.map((m, i) => `
        <div class="card" style="margin-bottom:8px">
          <div class="sub">#${i + 1} · 相关度 ${escapeHtml(String(m.score ?? "—"))}</div>
          <div style="white-space:pre-wrap;margin-top:4px">${escapeHtml(m.content || m.text || JSON.stringify(m))}</div>
        </div>`).join("");
    } catch (exc) {
      result.innerHTML = errorBox(exc);
    }
  });
}
