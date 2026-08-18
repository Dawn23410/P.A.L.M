/* MCP 工具台界面：工具列表 / 调用（契约端点：GET /api/mcp/tools、POST /api/mcp/call）。 */

import { get, post } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "MCP 工具台";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>MCP 工具台</h1>
    <div class="sub">已连接 MCP 工具 · 调用（契约端点 GET /api/mcp/tools）</div>
    <div id="mcp-body"><div class="sub">加载中…</div></div>`;

  const body = document.getElementById("mcp-body");
  (async () => {
    let j;
    try {
      j = await get("/api/mcp/tools");
    } catch (exc) {
      body.innerHTML = `<div class="panel">${errorBox(exc)}</div>` +
        `<div class="sub">契约：GET /api/mcp/tools → {tools: [{name, description, server}]}</div>`;
      return;
    }
    const tools = j.tools || [];
    body.innerHTML = `<div class="panel"><div class="p-title">工具清单（${tools.length}）</div>
      <table class="tbl"><tr><th>工具</th><th>所属服务</th><th>说明</th></tr>
      ${tools.map((t) => `<tr><td class="mono">${escapeHtml(t.name)}</td><td>${escapeHtml(t.server || "—")}</td><td>${escapeHtml(t.description || "")}</td></tr>`).join("") || `<tr><td colspan="3" class="sub">无已连接 MCP 工具</td></tr>`}
      </table></div>`;
  })();
}
