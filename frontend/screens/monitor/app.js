/* 运行监控界面：进程检测 / 模式解析（契约端点：GET /api/monitor/status）。 */

import { get } from "../../ui/api.js";
import { escapeHtml, errorBox, stateChip } from "../../ui/dom.js";

export const title = "运行监控";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>运行监控</h1>
    <div class="sub">游戏/专注进程检测 · 运行模式解析（契约端点 GET /api/monitor/status）</div>
    <div id="mon-body"><div class="sub">加载中…</div></div>`;

  const body = document.getElementById("mon-body");
  (async () => {
    let j;
    try {
      j = await get("/api/monitor/status");
    } catch (exc) {
      body.innerHTML = `<div class="panel">${errorBox(exc)}</div>` +
        `<div class="sub">契约：GET /api/monitor/status → {mode, game_running, processes: [...]}</div>`;
      return;
    }
    body.innerHTML = `
      <div class="grid" style="margin-bottom:12px">
        <div class="card"><div class="name">${escapeHtml(j.mode || "—")}</div><div class="title">当前模式</div></div>
        <div class="card"><div class="name">${stateChip(j.game_running)}</div><div class="title">游戏运行中</div></div>
      </div>
      <div class="panel"><div class="p-title">检测到的进程</div>
        <table class="tbl"><tr><th>名称</th><th>分类</th></tr>
        ${(j.processes || []).map((p) => `<tr><td>${escapeHtml(p.name || "—")}</td><td>${escapeHtml(p.kind || "—")}</td></tr>`).join("") || `<tr><td colspan="2" class="sub">无进程数据</td></tr>`}
        </table>
      </div>`;
  })();
}
