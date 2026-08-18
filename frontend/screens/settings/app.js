/* 应用设置界面：读写应用设置（契约端点：GET/POST /api/settings）。 */

import { get, post } from "../../ui/api.js";
import { escapeHtml, errorBox } from "../../ui/dom.js";

export const title = "应用设置";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>应用设置</h1>
    <div class="sub">外观 / Token 限额等应用设置（契约端点 GET/POST /api/settings）</div>
    <div class="panel">
      <div class="p-title">编辑</div>
      <textarea class="txt" id="set-editor" rows="12" style="width:100%;font-family:Consolas,monospace;font-size:12px" placeholder='{"dailyTokenLimit": 100, "monthlyTokenLimit": 500, ...}'></textarea>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button class="btn" id="set-load">载入当前</button>
        <button class="btn ghost" id="set-save">保存</button>
      </div>
      <div id="set-msg" class="sub" style="margin-top:8px"></div>
    </div>`;

  const editor = document.getElementById("set-editor");
  const msg = document.getElementById("set-msg");

  document.getElementById("set-load").addEventListener("click", async () => {
    try {
      const j = await get("/api/settings");
      editor.value = JSON.stringify(j || {}, null, 2);
      msg.textContent = "已载入当前设置";
    } catch (exc) {
      msg.textContent = "载入失败：" + exc.message;
    }
  });

  document.getElementById("set-save").addEventListener("click", async () => {
    let payload;
    try {
      payload = JSON.parse(editor.value);
    } catch (_) {
      msg.textContent = "JSON 格式错误";
      return;
    }
    try {
      await post("/api/settings", payload);
      msg.textContent = "已保存";
    } catch (exc) {
      msg.textContent = "保存失败：" + exc.message;
    }
  });
}
