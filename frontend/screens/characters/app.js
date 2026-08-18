/* 角色卡界面：人设卡片 / 好感度（契约端点：GET /api/characters、GET /api/affinity）。 */

import { get } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "角色卡";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>角色卡</h1>
    <div class="sub">人设卡片 · 好感度数值（契约端点 GET /api/characters、GET /api/affinity）</div>
    <div id="char-body"><div class="sub">加载中…</div></div>`;

  const body = document.getElementById("char-body");
  (async () => {
    let chars = [];
    try {
      const j = await get("/api/characters");
      chars = j.characters || j || [];
    } catch (exc) {
      body.innerHTML = `<div class="panel">${errorBox(exc)}</div>` +
        `<div class="sub">契约：GET /api/characters → {characters: [{id, name, persona, affinity}]}</div>`;
      return;
    }
    if (!chars.length) {
      body.innerHTML = `<div class="panel"><div class="sub">暂无角色卡。契约端点：GET /api/characters。</div></div>`;
      return;
    }
    body.innerHTML = `<div class="grid">${chars.map((c) => `
      <div class="card">
        <div class="name">${escapeHtml(c.name || c.id || "未命名")}</div>
        <div class="title">${escapeHtml(c.persona || "")}</div>
        <div style="margin-top:8px"><span class="chip">好感度 ${escapeHtml(String(c.affinity ?? "—"))}</span></div>
      </div>`).join("")}</div>`;
  })();
}
