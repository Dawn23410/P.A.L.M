/*
 * <ai-message> — 可复用的 AI 对话消息 UI 组件（Web Component，Shadow DOM 自包含）
 *
 * 内置能力：
 *   · Markdown 渲染（内嵌复用 <md-renderer>，支持 192 语言代码高亮 / emoji / 国旗 / 双主题）
 *   · Token 计数器（默认按多语言启发式估算；可注入精确 tokenizer 或由 host 直接给 tokens）
 *   · 延迟计数器（总耗时 + 可选首字延迟 TTFT）
 *   · 一键复制（复制原始 markdown；带"已复制"反馈；file:// 下回退 execCommand）
 *   · 重新生成（仅派发 ai-regenerate 事件，由 host 接入自己的后端，保持组件与具体后端解耦）
 *   · 运行沙箱（透传 sandbox 属性：JS/HTML/CSS 浏览器内执行；Python/Node.js/Bash 经后端 /api/run 执行）
 *
 * 依赖（需在宿主页通过 <script> 引入）：
 *   marked.min.js  purify.min.js  highlight.min.js  lang-loader.js
 *   emoji-common.js  emoji-loader.js  flag-polyfill.js  lang-bundle.js  emoji-full.js
 *   md-renderer.js   ← 本组件复用它的渲染管线
 *
 * 用法：
 *   <ai-message theme="dark" label="AI 助手"># 你好\n**世界**</ai-message>
 *   <ai-message id="m" endpoint="/api/last" poll="2000"></ai-message>
 *
 * 编程：
 *   const m = document.querySelector('ai-message');
 *   m.markdown = '...';            // 设置内容（自动重算估算 token）
 *   m.tokens   = 128;             // 注入精确输出 token 数（覆盖估算）
 *   m.latency  = 1234;            // 总生成耗时(ms)
 *   m.ttft     = 320;             // 首字延迟(ms，可选)
 *   m.loading  = true;            // 进入生成中态（显示 spinner、禁用按钮）
 *   m.tokenizer = fn;             // 自定义 token 估算函数 (text)=>number
 *
 * 事件（均 bubbles + composed，可在任意祖先监听）：
 *   'ai-regenerate' detail: { markdown, tokens, latency, ttft }
 *   'ai-copy'        detail: { text }
 */
(function () {
  "use strict";

  // ---------- 多语言 token 估算（启发式，非精确）----------
  // CJK 字符约 1 token/字；英文按词 ~1.3 token；标点 ~0.3 token。
  function estimateTokens(text) {
    if (!text) return 0;
    var cjkRe = /[぀-ヿ㐀-䶿一-鿿豈-﫿！-～]/g;
    var cjk = (text.match(cjkRe) || []).length;
    var rest = text.replace(cjkRe, " ");
    var words = (rest.match(/[A-Za-z0-9]+/g) || []).length;
    var punct = rest.replace(/[A-Za-z0-9\s]/g, "").length;
    var n = cjk + words * 1.3 + punct * 0.3;
    return Math.max(1, Math.round(n));
  }

  function fmtLatency(ms) {
    if (ms == null || isNaN(ms)) return null;
    if (ms < 1000) return ms + " ms";
    return (ms / 1000).toFixed(2) + " s";
  }

  function fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) { /* 忽略 */ }
  }

  var CSS = [
    ":host{display:block;box-sizing:border-box;",
    "  --aim-bg:#1b1f2a;--aim-bg2:#222736;--aim-text:#e6e9ef;--aim-muted:#9aa3b2;",
    "  --aim-border:#2a3040;--aim-accent:#5b8cff;--aim-btn:#2a3040;--aim-btn-hover:#343c50;}",
    ":host([theme='light']){--aim-bg:#ffffff;--aim-bg2:#f6f8fa;--aim-text:#1f2328;--aim-muted:#57606a;",
    "  --aim-border:#d0d7de;--aim-accent:#0969da;--aim-btn:#eef1f4;--aim-btn-hover:#e2e6ea;}",
    ":host([hidden]){display:none}",
    ".aim-root{background:var(--aim-bg);border:1px solid var(--aim-border);border-radius:12px;",
    "  overflow:hidden;color:var(--aim-text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',",
    "  Helvetica,Arial,'PingFang SC','Microsoft YaHei',sans-serif;}",
    ".aim-head{display:flex;align-items:center;gap:8px;padding:10px 14px;",
    "  background:var(--aim-bg2);border-bottom:1px solid var(--aim-border);font-size:13px;font-weight:600;}",
    ".aim-dot{width:8px;height:8px;border-radius:50%;background:var(--aim-accent);flex:none;",
    "  box-shadow:0 0 0 3px color-mix(in srgb,var(--aim-accent) 25%,transparent);}",
    ":host([loading]) .aim-dot{animation:pulse 1s ease-in-out infinite}",
    ".aim-role{color:var(--aim-text)}",
    ".aim-spin{width:14px;height:14px;border-radius:50%;border:2px solid var(--aim-muted);",
    "  border-top-color:var(--aim-accent);animation:spin .8s linear infinite;margin-left:2px;}",
    ".aim-body{padding:4px 14px 12px;}",
    "md-renderer{display:block}",
    ".aim-foot{display:flex;align-items:center;gap:10px;padding:8px 14px;",
    "  border-top:1px solid var(--aim-border);background:var(--aim-bg2);font-size:12px;color:var(--aim-muted);}",
    ".aim-stat{white-space:nowrap;font-variant-numeric:tabular-nums;}",
    ".aim-stat b{color:var(--aim-text);font-weight:600}",
    ".aim-spacer{flex:1}",
    ".aim-btn{appearance:none;border:1px solid var(--aim-border);background:var(--aim-btn);",
    "  color:var(--aim-text);font-size:12px;line-height:1;padding:6px 10px;border-radius:7px;cursor:pointer;",
    "  display:inline-flex;align-items:center;gap:5px;transition:background .15s,border-color .15s;}",
    ".aim-btn:hover{background:var(--aim-btn-hover)}",
    ".aim-btn:active{transform:translateY(1px)}",
    ".aim-btn:disabled{opacity:.5;cursor:not-allowed}",
    ".aim-btn.copied{border-color:var(--aim-accent);color:var(--aim-accent)}",
    "@keyframes spin{to{transform:rotate(360deg)}}",
    "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}",
    "@media (prefers-reduced-motion:reduce){.aim-spin,:host([loading]) .aim-dot{animation:none}}"
  ].join("");

  var TEMPLATE = [
    '<div class="aim-root">',
    '  <div class="aim-head">',
    '    <span class="aim-dot"></span>',
    '    <span class="aim-role"></span>',
    '    <span class="aim-spin" hidden></span>',
    '  </div>',
    '  <div class="aim-body"><md-renderer nostatus></md-renderer></div>',
    '  <div class="aim-foot">',
    '    <span class="aim-stat" data-token>≈ 0 tokens</span>',
    '    <span class="aim-stat" data-latency>⏱ —</span>',
    '    <span class="aim-spacer"></span>',
    '    <button class="aim-btn" data-copy type="button">复制</button>',
    '    <button class="aim-btn" data-regen type="button">重新生成</button>',
    '  </div>',
    '</div>'
  ].join("");

  class AiMessage extends HTMLElement {
    constructor() {
      super();
      this._md = "";
      this._explicitTokens = null;
      this._latency = null;
      this._ttft = null;
      this._tokenizer = estimateTokens;
      this._wired = false;
    }

    connectedCallback() {
      if (!this.shadowRoot) {
        var root = this.attachShadow({ mode: "open" });
        var style = document.createElement("style");
        style.textContent = CSS;
        var wrap = document.createElement("div");
        wrap.innerHTML = TEMPLATE;
        root.appendChild(style);
        root.appendChild(wrap.firstElementChild);
        this._r = root.querySelector("md-renderer");
        this._roleEl = root.querySelector(".aim-role");
        this._tokenEl = root.querySelector("[data-token]");
        this._latencyEl = root.querySelector("[data-latency]");
        this._spinEl = root.querySelector(".aim-spin");
        this._copyBtn = root.querySelector("[data-copy]");
        this._regenBtn = root.querySelector("[data-regen]");
      }
      if (!this._wired) {
        var self = this;
        this._copyBtn.addEventListener("click", function () { self.copy(); });
        this._regenBtn.addEventListener("click", function () { self.regenerate(); });
        this._wired = true;
      }
      this._roleEl.textContent = this.getAttribute("label") || this._defaultRole();
      if (!this.hasAttribute("theme")) this.setAttribute("theme", "dark");
      this._syncRenderer();
      this._renderToken();
      this._renderLatency();
      this._applyLoading();
    }

    disconnectedCallback() {
      clearTimeout(this._copyT);
    }

    static get observedAttributes() {
      return ["theme", "label", "role", "loading", "markdown", "sandbox"];
    }

    attributeChangedCallback(name, oldV, newV) {
      if (!this._r && name !== "markdown") return;
      if (name === "theme") {
        if (this._r) this._r.theme = this.getAttribute("theme") || "dark";
      } else if (name === "label" || name === "role") {
        if (this._roleEl) this._roleEl.textContent = this.getAttribute("label") || this._defaultRole();
      } else if (name === "loading") {
        this._applyLoading();
        this._renderLatency();
      } else if (name === "markdown") {
        this.markdown = this.getAttribute("markdown") || "";
      } else if (name === "sandbox") {
        if (this._r) {
          if (this.hasAttribute("sandbox")) this._r.setAttribute("sandbox", this.getAttribute("sandbox"));
          else this._r.removeAttribute("sandbox");
        }
      }
    }

    _defaultRole() {
      var r = (this.getAttribute("role") || "assistant").toLowerCase();
      return r === "user" ? "我" : (r === "system" ? "系统" : "AI 助手");
    }

    _syncRenderer() {
      if (!this._r) return;
      var t = this.getAttribute("theme") || "dark";
      if (this._r.theme !== t) this._r.theme = t;
      if (this.hasAttribute("sandbox")) this._r.setAttribute("sandbox", this.getAttribute("sandbox"));
      else this._r.removeAttribute("sandbox");
      this._r.markdown = this._md;
    }

    _renderToken() {
      if (!this._tokenEl) return;
      var n = (this._explicitTokens != null)
        ? this._explicitTokens : this._tokenizer(this._md || "");
      var approx = (this._explicitTokens == null) ? "≈ " : "";
      this._tokenEl.innerHTML = approx + "<b>" + n + "</b> tokens";
    }

    _renderLatency() {
      if (!this._latencyEl) return;
      if (this.hasAttribute("loading") && this._latency == null) {
        this._latencyEl.textContent = "生成中…";
        return;
      }
      var total = fmtLatency(this._latency);
      var ttft = fmtLatency(this._ttft);
      var s = "⏱ " + (total || "—");
      if (ttft) s += " · TTFT " + ttft;
      this._latencyEl.textContent = s;
    }

    _applyLoading() {
      var loading = this.hasAttribute("loading");
      if (this._spinEl) this._spinEl.hidden = !loading;
      if (this._copyBtn) this._copyBtn.disabled = loading;
      if (this._regenBtn) this._regenBtn.disabled = loading;
    }

    // ---- 公共 API ----
    get markdown() { return this._md; }
    set markdown(v) {
      this._md = v == null ? "" : String(v);
      if (this._r) this._r.markdown = this._md;
      this._renderToken();
    }
    setMarkdown(v) { this.markdown = v; }

    get tokens() { return this._explicitTokens; }
    set tokens(v) {
      this._explicitTokens = (v == null || isNaN(+v)) ? null : Math.max(0, Math.round(+v));
      this._renderToken();
    }

    get latency() { return this._latency; }
    set latency(v) { this._latency = (v == null || isNaN(+v)) ? null : +v; this._renderLatency(); }

    get ttft() { return this._ttft; }
    set ttft(v) { this._ttft = (v == null || isNaN(+v)) ? null : +v; this._renderLatency(); }

    get loading() { return this.hasAttribute("loading"); }
    set loading(v) {
      if (v) this.setAttribute("loading", "");
      else this.removeAttribute("loading");
      this._applyLoading();
      this._renderLatency();
    }

    get tokenizer() { return this._tokenizer; }
    set tokenizer(fn) { this._tokenizer = (typeof fn === "function") ? fn : estimateTokens; this._renderToken(); }

    get theme() { return this.getAttribute("theme") || "dark"; }
    set theme(v) {
      var t = (v === "light") ? "light" : "dark";
      if (this.getAttribute("theme") !== t) this.setAttribute("theme", t);
    }

    // 沙箱后端端点：设置后对话内 python/node/bash 代码块可经此后端执行
    get sandbox() { return this.getAttribute("sandbox") || ""; }
    set sandbox(v) {
      if (v) this.setAttribute("sandbox", v);
      else this.removeAttribute("sandbox");
    }

    copy() {
      var self = this;
      var text = this._md || "";
      var done = function () {
        self._flashCopy();
        self.dispatchEvent(new CustomEvent("ai-copy", {
          bubbles: true, composed: true, detail: { text: text }
        }));
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
      } else {
        fallbackCopy(text);
        done();
      }
    }

    _flashCopy() {
      if (!this._copyBtn) return;
      var b = this._copyBtn;
      b.classList.add("copied");
      var old = b.textContent;
      b.textContent = "✓ 已复制";
      clearTimeout(this._copyT);
      this._copyT = setTimeout(function () {
        b.classList.remove("copied");
        b.textContent = old;
      }, 1500);
    }

    regenerate() {
      this.dispatchEvent(new CustomEvent("ai-regenerate", {
        bubbles: true, composed: true,
        detail: { markdown: this._md, tokens: this._explicitTokens, latency: this._latency, ttft: this._ttft }
      }));
    }
  }

  if (typeof HTMLElement !== "undefined" && !customElements.get("ai-message")) {
    customElements.define("ai-message", AiMessage);
  }
  window.AiMessage = AiMessage;
})();
