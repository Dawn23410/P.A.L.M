/* Token 用量界面：台账 / 配额（契约端点：GET /api/token-usage）。 */

import { get } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "Token 用量";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>Token 用量</h1>
    <div class="sub">用量台账 · 配额状态（契约端点 GET /api/token-usage）</div>
    <div id="usage-body"><div class="sub">加载中…</div></div>`;

  const body = document.getElementById("usage-body");
  (async () => {
    let j;
    try {
      j = await get("/api/token-usage");
    } catch (exc) {
      body.innerHTML = `<div class="panel">${errorBox(exc)}</div>` +
        `<div class="sub">契约：GET /api/token-usage → {today, month, total, records: [...]}</div>`;
      return;
    }
    const records = (j.records || []).slice(0, 50);
    body.innerHTML = `
      <div class="grid" style="margin-bottom:12px">
        <div class="card"><div class="name">${escapeHtml(String(j.today ?? "—"))}</div><div class="title">今日用量</div></div>
        <div class="card"><div class="name">${escapeHtml(String(j.month ?? "—"))}</div><div class="title">本月用量</div></div>
        <div class="card"><div class="name">${escapeHtml(String(j.total ?? "—"))}</div><div class="title">累计用量</div></div>
      </div>
      <div class="panel"><div class="p-title">最近明细</div>
        <table class="tbl"><tr><th>时间</th><th>模型</th><th>Provider</th><th>Tokens</th></tr>
        ${records.map((r) => `<tr><td>${escapeHtml(r.ts || r.time || "—")}</td><td>${escapeHtml(r.model || "—")}</td><td>${escapeHtml(r.provider || "—")}</td><td>${escapeHtml(String(r.total_tokens ?? "—"))}</td></tr>`).join("") || `<tr><td colspan="4" class="sub">暂无记录</td></tr>`}
        </table>
      </div>`;
  })();
}
