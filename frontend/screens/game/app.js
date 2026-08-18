/* 游戏生态界面：等级/经验/星砂/每日任务/商城（契约端点：GET /api/game/state 等）。 */

import { get } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "游戏生态";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>游戏生态</h1>
    <div class="sub">经验/等级 · 星砂货币 · 每日任务 · 商城（契约端点 GET /api/game/state、GET /api/game/shop）</div>
    <div id="game-body"><div class="sub">加载中…</div></div>`;

  const body = document.getElementById("game-body");
  (async () => {
    let s;
    try {
      s = await get("/api/game/state");
    } catch (exc) {
      body.innerHTML = `<div class="panel">${errorBox(exc)}</div>` +
        `<div class="sub">契约：GET /api/game/state → {level, stage, total_exp, currency, streak_days, daily_tasks: [...]}</div>`;
      return;
    }
    const tasks = (s.daily_tasks || []).map((t) => `
      <tr><td>${escapeHtml(t.label || t.key)}</td><td>${t.done ? "✅" : "⬜"}</td><td>${escapeHtml(String(t.reward ?? ""))}</td></tr>`).join("");
    body.innerHTML = `
      <div class="grid" style="margin-bottom:12px">
        <div class="card"><div class="name">${escapeHtml(String(s.level ?? "—"))} 级</div><div class="title">阶段 ${escapeHtml(String(s.stage ?? "—"))}</div></div>
        <div class="card"><div class="name">${escapeHtml(String(s.total_exp ?? "—"))}</div><div class="title">总经验</div></div>
        <div class="card"><div class="name">${escapeHtml(String(s.currency ?? "—"))} ⭐</div><div class="title">星砂</div></div>
        <div class="card"><div class="name">${escapeHtml(String(s.streak_days ?? "—"))} 天</div><div class="title">连续登录</div></div>
      </div>
      <div class="panel"><div class="p-title">每日任务</div>
        <table class="tbl"><tr><th>任务</th><th>完成</th><th>奖励</th></tr>${tasks || `<tr><td colspan="3" class="sub">无任务数据</td></tr>`}</table>
      </div>`;
  })();
}
