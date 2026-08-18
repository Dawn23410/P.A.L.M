/* 对话界面：SSE 流式对话（契约端点：POST /api/chat 事件流 + GET /api/chat/file-support）。 */

import { get, stream } from "../../ui/api.js";
import { escapeHtml } from "../../ui/dom.js";

export const title = "对话";

export function mount(root, ctx) {
  root.innerHTML = `
    <h1>对话</h1>
    <div class="sub">SSE 流式 · 思维链增量（delta/reasoning）· 契约端点 POST /api/chat</div>
    <div class="panel">
      <div class="p-title">会话</div>
      <div id="chat-log" style="min-height:200px;max-height:420px;overflow:auto;display:flex;flex-direction:column;gap:8px;margin-bottom:10px">
        <div class="sub">输入下方消息开始对话；后端未连接时提示降级。</div>
      </div>
      <div style="display:flex;gap:8px">
        <input class="txt" id="chat-input" style="flex:1" placeholder="输入消息…（Enter 发送）" />
        <button class="btn" id="chat-send">发送</button>
      </div>
    </div>`;

  const log = document.getElementById("chat-log");
  const input = document.getElementById("chat-input");
  let current = null; // 当前流式回复容器

  function append(kind, text) {
    const div = document.createElement("div");
    div.style.cssText = kind === "user"
      ? "align-self:flex-end;background:var(--accent);color:#fff;padding:8px 12px;border-radius:10px;max-width:75%;white-space:pre-wrap"
      : "align-self:flex-start;background:var(--bg-hover);padding:8px 12px;border-radius:10px;max-width:75%;white-space:pre-wrap";
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function thinking(text) {
    const div = document.createElement("div");
    div.className = "sub";
    div.style.cssText = "align-self:flex-start;font-style:italic;padding:2px 12px";
    div.textContent = text;
    log.appendChild(div);
    return div;
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    append("user", text);
    const reply = append("assistant", "");
    try {
      let draft = "";
      let reason = "";
      const stop = stream("/api/chat", { model: "", messages: [{ role: "user", content: text }] }, {
        onEvent: (ev) => {
          if (ev.reasoning && ev.reasoning !== reason) {
            reason = ev.reasoning;
            if (!current) { current = thinking("💭 " + reason); }
          }
          if (ev.delta) {
            draft += ev.delta;
            reply.textContent = draft;
            if (current) current.remove();
            log.scrollTop = log.scrollHeight;
          }
          if (ev.type === "error") {
            reply.textContent = "⚠️ " + (ev.delta || "生成失败");
          }
        },
        onError: (exc) => {
          reply.textContent = "⚠️ " + exc.message;
        },
      });
      current = stop; // 简化：保留引用以便未来支持中止
    } catch (exc) {
      reply.textContent = "⚠️ " + exc.message;
    }
  }

  document.getElementById("chat-send").addEventListener("click", send);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

  // 探测文件能力（契约端点，缺失即忽略）
  get("/api/chat/file-support").catch(() => {});
}
