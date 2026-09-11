/*!
 * <md-renderer> —— 独立可复用的 Markdown 渲染 UI 控件（Web Component）
 *
 * 特性：
 *  - 自包含：内部用 Shadow DOM 隔离样式，可直接拖入任意 UI 使用，不污染宿主页面。
 *  - 完整渲染管线：marked + DOMPurify + highlight.js（192 语言按需加载）+ emoji 二级加载 + 国旗 polyfill。
 *  - 多种输入方式：
 *      · 后端拉取：<md-renderer endpoint="/api/last" poll="2000"> 自动轮询后端 markdown 文本。
 *      · 编程赋值：el.markdown = "..."; 或 el.setMarkdown("...");
 *      · 方法刷新：el.refresh();
 *  - 主题：theme="dark"（默认）/ "light"，可随时切换。
 *  - 空态：无内容时显示 placeholder 文本，而非空白背景。
 *  - 运行沙箱：代码块自动出现「▶ 运行」按钮。
 *      · JS / HTML / CSS 在浏览器内沙箱（独立 sandbox iframe）执行，零后端依赖。
 *      · Python / Node.js / Bash 经 sandbox="/api/run" 属性指向的后端端点执行（该端点需显式开启）。
 *
 * 依赖（宿主页面需引入，或本控件在 shim 中按需加载）：
 *  vendor/marked.min.js, vendor/purify.min.js, vendor/highlight.min.js,
 *  vendor/lang/aliases.js, vendor/lang-loader.js, vendor/emoji-common.js,
 *  vendor/emoji-loader.js, vendor/flag-polyfill.js
 */
(function () {
  "use strict";

  // ===== highlight.js 主题（内联，按 :host([theme]) 双色适配；背景由容器 var 提供故透明）=====
  function scopeTheme(sel, arr) {
    return arr.map(function (r) { return sel + " " + r; }).join("");
  }
  var HLJS_BASE = [
    "pre code.hljs{display:block;overflow-x:auto;padding:1em}",
    "code.hljs{padding:3px 5px}"
  ];
  var HLJS_DARK = [
    ".hljs{color:#c9d1d9;background:transparent}",
    ".hljs-doctag,.hljs-keyword,.hljs-meta .hljs-keyword,.hljs-template-tag,.hljs-template-variable,.hljs-type,.hljs-variable.language_{color:#ff7b72}",
    ".hljs-title,.hljs-title.class_,.hljs-title.class_.inherited__,.hljs-title.function_{color:#d2a8ff}",
    ".hljs-attr,.hljs-attribute,.hljs-literal,.hljs-meta,.hljs-number,.hljs-operator,.hljs-selector-attr,.hljs-selector-class,.hljs-selector-id,.hljs-variable{color:#79c0ff}",
    ".hljs-meta .hljs-string,.hljs-regexp,.hljs-string{color:#a5d6ff}",
    ".hljs-built_in,.hljs-symbol{color:#ffa657}",
    ".hljs-code,.hljs-comment,.hljs-formula{color:#8b949e}",
    ".hljs-name,.hljs-quote,.hljs-selector-pseudo,.hljs-selector-tag{color:#7ee787}",
    ".hljs-subst{color:#c9d1d9}",
    ".hljs-section{color:#1f6feb;font-weight:700}",
    ".hljs-bullet{color:#f2cc60}",
    ".hljs-emphasis{color:#c9d1d9;font-style:italic}",
    ".hljs-strong{color:#c9d1d9;font-weight:700}",
    ".hljs-addition{color:#aff5b4;background-color:#033a16}",
    ".hljs-deletion{color:#ffdcd7;background-color:#67060c}"
  ];
  var HLJS_LIGHT = [
    ".hljs{color:#24292e;background:transparent}",
    ".hljs-doctag,.hljs-keyword,.hljs-meta .hljs-keyword,.hljs-template-tag,.hljs-template-variable,.hljs-type,.hljs-variable.language_{color:#d73a49}",
    ".hljs-title,.hljs-title.class_,.hljs-title.class_.inherited__,.hljs-title.function_{color:#6f42c1}",
    ".hljs-attr,.hljs-attribute,.hljs-literal,.hljs-meta,.hljs-number,.hljs-operator,.hljs-selector-attr,.hljs-selector-class,.hljs-selector-id,.hljs-variable{color:#005cc5}",
    ".hljs-meta .hljs-string,.hljs-regexp,.hljs-string{color:#032f62}",
    ".hljs-built_in,.hljs-symbol{color:#e36209}",
    ".hljs-code,.hljs-comment,.hljs-formula{color:#6a737d}",
    ".hljs-name,.hljs-quote,.hljs-selector-pseudo,.hljs-selector-tag{color:#22863a}",
    ".hljs-subst{color:#24292e}",
    ".hljs-section{color:#005cc5;font-weight:700}",
    ".hljs-bullet{color:#735c0f}",
    ".hljs-emphasis{color:#24292e;font-style:italic}",
    ".hljs-strong{color:#24292e;font-weight:700}",
    ".hljs-addition{color:#22863a;background-color:#f0fff4}",
    ".hljs-deletion{color:#b31d28;background-color:#ffeef0}"
  ];
  var HLJS_THEME = HLJS_BASE.join("")
    + scopeTheme(":host([theme='dark'])", HLJS_DARK)
    + scopeTheme(":host([theme='light'])", HLJS_LIGHT);

  // ===== 浏览器内 JS 执行沙箱（独立 opaque-origin iframe，仅允许脚本；捕获 console 与未捕获错误）=====
  var JS_SANDBOX_SRC = "<!doctype html><html><head><meta charset=\"utf-8\"></head><body><scr" + "ipt>" +
    "(function(){" +
    "function post(o){o.__mdr=1;parent.postMessage(o,\"*\");}" +
    "[\"log\",\"info\",\"warn\",\"error\",\"debug\"].forEach(function(k){var o=console[k];" +
    "console[k]=function(){var a=[].slice.call(arguments).map(function(x){" +
    "try{return typeof x===\"object\"&&x!==null?JSON.stringify(x):String(x)}catch(e){return String(x)}});" +
    "post({type:k,text:a.join(\" \"),rid:window.__rid});};});" +
    "window.onerror=function(m,s,l,c,e){post({type:\"error\",text:String(m)+\" (line \"+(l||0)+\")\",rid:window.__rid});" +
    "post({done:1,rid:window.__rid});};" +
    "window.addEventListener(\"message\",function(ev){var d=ev.data;if(!d||!d.__mdrRun)return;window.__rid=d.rid;" +
    "try{(0,eval)(d.code);}catch(e){post({type:\"error\",text:String(e&&e.message||e),rid:d.rid});}" +
    "post({done:1,rid:d.rid});});" +
    "})();" +
    "</scr" + "ipt></body></html>";

  // ===== 相对路径加载器垫片（file:// 与 http 均可用，加载 192 语言 bundle + emoji-full）=====
  function ensureShim() {
    if (window.__mdrShimInstalled) return;
    window.__mdrShimInstalled = true;
    if (window.hljs) {
      var loading = Object.create(null);
      var sessionLoaded = Object.create(null);
      var readyHandler = null;
      var THRESHOLD = 10;
      var IDLE_MS = 3 * 60 * 60 * 1000;
      var idleTimer = null;
      function isRegistered(n) {
        return !!(window.hljs && window.hljs.getLanguage && window.hljs.getLanguage(n));
      }
      function resolve(raw) {
        if (!raw) return null;
        var n = String(raw).toLowerCase();
        if (window.HLJS_ALIASES && window.HLJS_ALIASES[n]) n = window.HLJS_ALIASES[n];
        return n;
      }
      function fireReady(n, ok) { if (readyHandler) { try { readyHandler(n, ok); } catch (e) {} } }
      function resetIdle() {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(function () {
          for (var k in sessionLoaded) delete sessionLoaded[k];
        }, IDLE_MS);
      }
      var bundleLoading = null;
      function ensureBundle() {
        if (bundleLoading) return bundleLoading;
        bundleLoading = new Promise(function (res) {
          var s = document.createElement("script");
          s.src = "vendor/lang-bundle.js";
          s.onload = function () { res(true); };
          s.onerror = function () { res(false); };
          document.head.appendChild(s);
        });
        return bundleLoading;
      }
      function ensure(name, opts) {
        opts = opts || {};
        return new Promise(function (res) {
          if (isRegistered(name)) { sessionLoaded[name] = true; resetIdle(); res(true); return; }
          ensureBundle().then(function (ok) {
            var ok2 = !!(ok && isRegistered(name));
            sessionLoaded[name] = ok2;
            fireReady(name, ok2);
            resetIdle();
            res(ok2);
          });
        });
      }
      window.LangLoader = {
        resolve: resolve, isRegistered: isRegistered, ensure: ensure,
        preload: function () {}, init: function () { return Promise.resolve(); },
        setReadyHandler: function (fn) { readyHandler = fn; },
        get THRESHOLD() { return THRESHOLD; }
      };
    }
    (function () {
      var FULL_URL = "vendor/emoji-full.js";
      var loaded = false, loading = null, readyHandler = null;
      var seenThisRender = new Set();
      var sessionUse = Object.create(null);
      var pending = Object.create(null);
      var saveTimer = null;
      function isCommon(n) {
        return !!(window.EMOJI_MAP && Object.prototype.hasOwnProperty.call(window.EMOJI_MAP, n));
      }
      function beginRender() { seenThisRender = new Set(); }
      function endRender() { var s = seenThisRender; seenThisRender = new Set(); return s; }
      function track(name) {
        if (!name) return;
        sessionUse[name] = (sessionUse[name] || 0) + 1;
        pending[name] = (pending[name] || 0) + 1;
        if (saveTimer) return;
        saveTimer = setTimeout(function () { saveTimer = null; pending = Object.create(null); }, 1000);
      }
      function note(name) {
        if (loaded && window.EMOJI_FULL &&
            !Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, name)) return;
        seenThisRender.add(name);
        ensureFull();
      }
      function ensureFull() {
        if (loaded) return Promise.resolve(true);
        if (loading) return loading;
        loading = new Promise(function (res) {
          var sc = document.createElement("script");
          sc.src = FULL_URL;
          sc.onload = function () {
            if (window.EMOJI_FULL && window.EMOJI_MAP) {
              for (var k in window.EMOJI_FULL) {
                if (Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, k))
                  window.EMOJI_MAP[k] = window.EMOJI_FULL[k];
              }
              loaded = true; loading = null; res(true);
              if (readyHandler) readyHandler();
            } else { loading = null; res(false); }
          };
          sc.onerror = function () { loading = null; res(false); };
          document.head.appendChild(sc);
        });
        return loading;
      }
      function getStats() {
        var total = 0, distinct = 0, commonDistinct = 0, commonOcc = 0;
        for (var k in sessionUse) {
          if (!Object.prototype.hasOwnProperty.call(sessionUse, k)) continue;
          distinct++; total += sessionUse[k];
          if (isCommon(k)) { commonDistinct++; commonOcc += sessionUse[k]; }
        }
        return {
          total: total, distinct: distinct,
          commonDistinct: commonDistinct, uncommonDistinct: distinct - commonDistinct,
          commonHits: commonOcc, uncommonHits: total - commonOcc,
          hitRate: distinct ? commonDistinct / distinct : 1, fullLoaded: loaded
        };
      }
      window.EmojiLoader = {
        note: note, track: track, beginRender: beginRender, endRender: endRender,
        ensureFull: ensureFull, setReadyHandler: function (fn) { readyHandler = fn; },
        isLoaded: function () { return loaded; }, getStats: getStats
      };
    })();
  }

  // ===== emoji :shortcode: 扩展（仅安装一次）=====
  function ensureEmojiExt() {
    if (window.__mdrEmojiExt || !window.marked) return;
    window.__mdrEmojiExt = true;
    if (!window.EMOJI_MAP) return;
    try {
      marked.use({
        extensions: [{
          name: "emoji",
          level: "inline",
          start(src) { var i = src.indexOf(":"); return i < 0 ? undefined : i; },
          tokenizer(src) {
            var m = /^:([a-z0-9_+\-]+):/i.exec(src);
            if (m) {
              var key = m[1].toLowerCase();
              if (Object.prototype.hasOwnProperty.call(window.EMOJI_MAP, key)) {
                if (window.EmojiLoader) EmojiLoader.track(key);
                return { type: "emoji", raw: m[0], text: window.EMOJI_MAP[key] };
              }
              if (window.EmojiLoader) { EmojiLoader.track(key); EmojiLoader.note(key); }
            }
            return undefined;
          },
          renderer(token) { return token.text; }
        }]
      });
    } catch (e) { /* marked 已带扩展则忽略 */ }
  }

  // ===== 全局实例注册表（语言/emoji 就绪后统一重渲染）=====
  var INSTANCES = new Set();
  function rerenderAll() {
    INSTANCES.forEach(function (inst) { try { inst._render(); } catch (e) {} });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ===== 组件样式 =====
  var CSS = [
    ":host{display:block;width:100%;height:100%;box-sizing:border-box;",
    "  --mdr-panel:#1b1f2a;--mdr-panel-2:#222736;--mdr-text:#e6e9ef;--mdr-muted:#9aa3b2;",
    "  --mdr-border:#2a3040;--mdr-code-bg:#0d1117;--mdr-accent:#5b8cff;",
    "  --mdr-code-soft:rgba(0,0,0,.28);--mdr-gutter:#5b6677;--mdr-gutter-bg:rgba(0,0,0,.18);}",
    ":host([theme='light']){--mdr-panel:#ffffff;--mdr-panel-2:#f6f8fa;--mdr-text:#1f2328;",
    "  --mdr-muted:#57606a;--mdr-border:#d0d7de;--mdr-code-bg:#f6f8fa;--mdr-accent:#0969da;",
    "  --mdr-code-soft:rgba(27,31,35,.06);--mdr-gutter:#6a737d;--mdr-gutter-bg:rgba(27,31,35,.04);}",
    ":host{color-scheme:dark}",
    ":host([theme='light']){color-scheme:light}",
    ".mdr-root{display:flex;flex-direction:column;height:100%;background:var(--mdr-panel);",
    "  color:var(--mdr-text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,",
    "  'PingFang SC','Microsoft YaHei',sans-serif;font-size:15px;}",
    ".mdr-content{flex:1;overflow-y:auto;padding:20px 22px;line-height:1.7;}",
    ".mdr-content>:first-child{margin-top:0}",
    ".mdr-content h1,.mdr-content h2,.mdr-content h3,.mdr-content h4{line-height:1.3;margin:1.1em 0 .5em;font-weight:600}",
    ".mdr-content h1{font-size:1.7em;border-bottom:1px solid var(--mdr-border);padding-bottom:.3em}",
    ".mdr-content h2{font-size:1.4em;border-bottom:1px solid var(--mdr-border);padding-bottom:.3em}",
    ".mdr-content h3{font-size:1.2em}",
    ".mdr-content h4{font-size:1.05em}",
    ".mdr-content p{margin:.6em 0}",
    ".mdr-content a{color:var(--mdr-accent);text-decoration:none}",
    ".mdr-content a:hover{text-decoration:underline}",
    ".mdr-content code{background:var(--mdr-code-bg);padding:.15em .4em;border-radius:5px;font-size:.88em;",
    "  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}",
    ".mdr-content pre{background:var(--mdr-code-bg);border:1px solid var(--mdr-border);border-radius:8px;margin:.7em 0;overflow:auto}",
    ".mdr-content pre code{background:none;padding:0;font-size:.88em;line-height:1.6}",
    ".mdr-content blockquote{margin:.6em 0;padding:0 1em;color:var(--mdr-muted);border-left:4px solid var(--mdr-border)}",
    ".mdr-content table{border-collapse:collapse;margin:.6em 0;display:block;overflow:auto;width:max-content;max-width:100%}",
    ".mdr-content th,.mdr-content td{border:1px solid var(--mdr-border);padding:6px 13px}",
    ".mdr-content tr:nth-child(2n){background:rgba(127,127,127,.08)}",
    ".mdr-content img{max-width:100%;border-radius:6px}",
    ".mdr-content ul,.mdr-content ol{padding-left:2em;margin:.5em 0}",
    ".mdr-content hr{border:none;border-top:1px solid var(--mdr-border);margin:1.4em 0}",
    ".mdr-content input[type=checkbox]{margin-right:.4em}",
    ".mdr-empty{color:var(--mdr-muted);font-style:italic;padding:8px 2px}",
    ".mdr-status{flex:none;display:flex;gap:14px;align-items:center;flex-wrap:wrap;",
    "  padding:6px 14px;font-size:12px;color:var(--mdr-muted);",
    "  background:var(--mdr-panel-2);border-top:1px solid var(--mdr-border);}",
    ".mdr-status b.ok{color:#36d399}.mdr-status b.warn{color:#f0c040}.mdr-status b.err{color:#ff6b6b}",
    /* 代码块：语言标题栏 + 行号（与项目 app.js 同款结构，仅类名带 mdr- 前缀隔离）*/
    ".code-block{display:flex;flex-direction:column;background:var(--mdr-code-bg);",
    "  border:1px solid var(--mdr-border);border-radius:8px;margin:.7em 0;overflow:hidden}",
    ".code-header{display:flex;align-items:center;gap:8px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
    "  font-size:12px;color:var(--mdr-muted);background:var(--mdr-code-soft);",
    "  border-bottom:1px solid var(--mdr-border);padding:4px 12px;user-select:none}",
    ".code-header .ch-lang{font-weight:600;color:var(--mdr-text)}",
    ".code-header .ch-spacer{flex:1}",
    ".run-btn{flex:none;cursor:pointer;border:1px solid var(--mdr-border);background:var(--mdr-panel-2);",
    "  color:var(--mdr-accent);font:inherit;font-size:12px;line-height:1;padding:3px 9px;border-radius:6px}",
    ".run-btn:hover{background:var(--mdr-accent);color:#fff;border-color:var(--mdr-accent)}",
    ".run-btn:disabled{opacity:.6;cursor:default}",
    ".mdr-output{flex:none;border-top:1px dashed var(--mdr-border);background:var(--mdr-panel-2)}",
    ".mdr-output[hidden]{display:none}",
    ".mdr-output .out-head{font-size:11px;color:var(--mdr-muted);padding:4px 12px;border-bottom:1px solid var(--mdr-border)}",
    ".mdr-output pre{margin:0;padding:8px 12px;white-space:pre-wrap;word-break:break-word;",
    "  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:var(--mdr-text);max-height:300px;overflow:auto}",
    ".mdr-output pre.err{color:#ff8e8e}",
    ".mdr-output .notice{padding:8px 12px;color:var(--mdr-muted);font-style:italic}",
    ".mdr-run-iframe{width:100%;height:220px;border:0;display:block;background:#fff}",
    ".code-body{display:flex;flex-direction:row;min-width:0}",
    ".code-block pre{margin:0;border:none;border-radius:0;flex:1;min-width:0}",
    ".code-block pre code{padding:1em;font-size:.88em;line-height:1.6}",
    ".ln-gutter{flex:none;text-align:right;padding:1em 8px;color:var(--mdr-gutter);background:var(--mdr-gutter-bg);",
    "  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em;line-height:1.6;",
    "  user-select:none;white-space:pre;overflow:hidden}",
    ".emoji-flag{height:1.1em;width:1.4em;vertical-align:-.15em;margin:0 1px;border-radius:2px;display:inline-block}"
  ].join("");

  // ===== 组件类 =====
  class MdRenderer extends HTMLElement {
    constructor() {
      super();
      this._md = "";
      this._failed = new Set();
      this._pollTimer = null;
      var root = this.attachShadow({ mode: "open" });
      var style = document.createElement("style");
      style.textContent = HLJS_THEME + CSS;
      var wrap = document.createElement("div");
      wrap.className = "mdr-root";
      var content = document.createElement("div");
      content.className = "mdr-content";
      var status = document.createElement("div");
      status.className = "mdr-status";
      wrap.appendChild(content);
      wrap.appendChild(status);
      root.appendChild(style);
      root.appendChild(wrap);
      this._content = content;
      this._status = status;
    }

    static get observedAttributes() { return ["endpoint", "poll", "theme", "placeholder", "nostatus", "sandbox"]; }

    connectedCallback() {
      ensureShim();
      ensureEmojiExt();
      if (window.LangLoader) LangLoader.setReadyHandler(function () { rerenderAll(); });
      if (window.EmojiLoader) EmojiLoader.setReadyHandler(function () { rerenderAll(); });
      INSTANCES.add(this);
      // 默认暗色；仅当未显式设置时才落属性，避免重复触发 attributeChangedCallback
      if (!this.hasAttribute("theme")) {
        this.setAttribute("theme", "dark"); // 会触发 attributeChangedCallback -> _render
      } else {
        this._render();
      }
      this._applyNoStatus();
      this._startPolling();
      this._updateStatus();
    }

    disconnectedCallback() {
      INSTANCES.delete(this);
      this._stopPolling();
    }

    attributeChangedCallback(name, oldV, newV) {
      if (name === "theme") { this._render(); }
      else if (name === "endpoint") { this._startPolling(); }
      else if (name === "poll") { this._startPolling(); }
      else if (name === "placeholder") { this._render(); }
      else if (name === "nostatus") { this._applyNoStatus(); }
    }

    _applyNoStatus() {
      if (!this._status) return;
      this._status.style.display = this.hasAttribute("nostatus") ? "none" : "";
    }

    // ---- 公共 API ----
    set markdown(v) { this._md = v == null ? "" : String(v); this._render(); this._updateStatus(); }
    get markdown() { return this._md; }
    setMarkdown(v) { this.markdown = v; }

    // 主题反射属性：el.theme = "light" | "dark"
    get theme() { return this.getAttribute("theme") || "dark"; }
    set theme(v) {
      var t = (v === "light") ? "light" : "dark";
      if (this.getAttribute("theme") !== t) this.setAttribute("theme", t);
      // attributeChangedCallback 已负责重渲染，无需在此调用，避免重复
    }

    // 沙箱后端端点；设置后 python/node/bash 代码块可经此执行
    get sandbox() { return this.getAttribute("sandbox") || ""; }
    set sandbox(v) { if (v) this.setAttribute("sandbox", v); else this.removeAttribute("sandbox"); }

    async refresh() {
      var ep = this.getAttribute("endpoint");
      if (!ep) return;
      try {
        var r = await fetch(ep, { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        var ct = r.headers.get("content-type") || "";
        var text;
        if (ct.indexOf("application/json") >= 0) {
          var d = await r.json();
          text = d.markdown != null ? d.markdown : (d.content != null ? d.content : "");
          this._updatedAt = d.updated_at || 0;
        } else {
          text = await r.text();
        }
        this._md = text || "";
        this._render();
        this._updateStatus();
      } catch (e) {
        this._setStatusError("拉取失败：" + e.message);
      }
    }

    // ---- 内部渲染 ----
    _startPolling() {
      this._stopPolling();
      var ep = this.getAttribute("endpoint");
      var poll = parseInt(this.getAttribute("poll") || "2000", 10);
      if (!ep || !poll || poll <= 0) return;
      var self = this;
      this.refresh();
      this._pollTimer = setInterval(function () { self.refresh(); }, poll);
    }
    _stopPolling() {
      if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
    }

    _mdHTML(text) {
      var html = "";
      try {
        html = window.marked ? marked.parse(text || "") : (text || "");
      } catch (e) {
        html = escapeHtml(text || "");
      }
      if (window.DOMPurify) {
        html = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
      }
      return html;
    }

    _render() {
      var txt = this._md || "";
      if (!txt.trim()) {
        var ph = this.getAttribute("placeholder") || "等待 markdown 输入…";
        this._content.innerHTML = '<div class="mdr-empty">' + escapeHtml(ph) + "</div>";
        if (window.FlagPolyfill) FlagPolyfill.process(this._content);
        return;
      }
      this._content.innerHTML = this._mdHTML(txt);
      if (window.FlagPolyfill) FlagPolyfill.process(this._content);
      this._highlight(this._content);
      this._addLineNumbers(this._content);
    }

    _highlight(host) {
      if (!window.hljs) return;
      var self = this;
      host.querySelectorAll("pre code").forEach(function (code) {
        var m = (code.className || "").match(/language-([\w+#.\-]+)/);
        var raw = m ? m[1] : null;
        var lang = raw ? (window.LangLoader ? LangLoader.resolve(raw) : raw.toLowerCase()) : null;
        if (!lang || lang === "plaintext" || lang === "plain") {
          try { hljs.highlightElement(code); } catch (e) {}
          return;
        }
        if (window.LangLoader && LangLoader.isRegistered(lang)) {
          try { hljs.highlightElement(code); } catch (e) {}
          return;
        }
        if (self._failed.has(lang)) return;
        self._failed.add(lang);
        if (window.LangLoader) LangLoader.ensure(lang);
      });
    }

    _addLineNumbers(host) {
      var self = this;
      host.querySelectorAll("pre").forEach(function (pre) {
        if (pre.parentNode && pre.parentNode.classList &&
            pre.parentNode.classList.contains("code-block")) return;
        var code = pre.querySelector("code");
        if (!code) return;
        var text = code.textContent || "";
        var lines = text.replace(/\n+$/, "").split("\n");
        var m = (code.className || "").match(/language-([\w+#.\-]+)/);
        var raw = m ? m[1] : null;
        var norm = self._normalizeLang(raw);
        var lang = raw ? raw : (text.trim() ? "text" : "");
        var block = document.createElement("div");
        block.className = "code-block";
        var header = null;
        if (raw) {
          header = document.createElement("div");
          header.className = "code-header";
          var langSpan = document.createElement("span");
          langSpan.className = "ch-lang";
          langSpan.textContent = "# " + lang;
          header.appendChild(langSpan);
          var spacer = document.createElement("span");
          spacer.className = "ch-spacer";
          header.appendChild(spacer);
          if (norm && self._isRunnable(norm)) {
            var btn = document.createElement("button");
            btn.className = "run-btn";
            btn.type = "button";
            btn.textContent = "▶ 运行";
            btn.addEventListener("click", function () {
              self._runBlock(norm, code, block);
            });
            header.appendChild(btn);
          }
        }
        var body = document.createElement("div");
        body.className = "code-body";
        if (lines.length > 1) {
          var gutter = document.createElement("div");
          gutter.className = "ln-gutter";
          gutter.textContent = lines.map(function (_, i) { return i + 1; }).join("\n");
          body.appendChild(gutter);
        }
        pre.parentNode.insertBefore(block, pre);
        if (header) block.appendChild(header);
        block.appendChild(body);
        body.appendChild(pre);
        var out = document.createElement("div");
        out.className = "mdr-output";
        out.hidden = true;
        block.appendChild(out);
      });
    }

    // ===== 运行沙箱 =====
    _normalizeLang(raw) {
      if (!raw) return null;
      var n = String(raw).toLowerCase();
      var map = { python: "python", py: "python", node: "node", javascript: "js",
        js: "js", html: "html", css: "css", bash: "bash", sh: "bash", shell: "bash" };
      return map[n] || null;
    }
    _isRunnable(norm) {
      return norm === "js" || norm === "html" || norm === "css" ||
             norm === "python" || norm === "node" || norm === "bash";
    }

    // 点击 Run 的统一入口
    _runBlock(norm, codeEl, block) {
      var code = codeEl.textContent || "";
      var out = block.querySelector(".mdr-output");
      var btn = block.querySelector(".run-btn");
      if (norm === "js") return this._runBrowserJS(code, out, btn);
      if (norm === "html") return this._runBrowserHTML(code, out, btn);
      if (norm === "css") return this._runBrowserCSS(code, out, btn);
      return this._runServer(norm, code, out, btn);
    }

    // —— 浏览器内：JavaScript（独立 sandbox iframe，捕获 console 与未捕获错误）——
    _runBrowserJS(code, out, btn) {
      out.hidden = false;
      out.innerHTML = '<div class="out-head">运行输出（浏览器沙箱 · 独立 iframe）</div>';
      var pre = document.createElement("pre");
      out.appendChild(pre);
      var iframe = document.createElement("iframe");
      iframe.setAttribute("sandbox", "allow-scripts");
      iframe.style.display = "none";
      (document.body || document.documentElement).appendChild(iframe);
      var rid = Math.random().toString(36).slice(2);
      var done = false;
      var self = this;
      var timer = setTimeout(function () {
        if (done) return; done = true;
        pre.className = "err"; pre.textContent += "\n…超时（5s）";
        cleanup();
      }, 5000);
      function append(text, isErr) {
        if (isErr) pre.className = "err";
        pre.textContent += text + "\n";
      }
      function cleanup() {
        clearTimeout(timer);
        window.removeEventListener("message", onMsg);
        try { iframe.remove(); } catch (e) {}
        if (btn) { btn.disabled = false; btn.textContent = "▶ 运行"; }
      }
      function onMsg(ev) {
        var d = ev.data;
        if (!d || d.__mdr !== 1 || d.rid !== rid) return;
        if (d.type) append("[" + d.type + "] " + d.text, d.type === "error");
        if (d.done) { done = true; cleanup(); }
      }
      window.addEventListener("message", onMsg);
      iframe.onload = function () {
        iframe.contentWindow.postMessage({ __mdrRun: true, code: code, rid: rid }, "*");
      };
      iframe.srcdoc = JS_SANDBOX_SRC;
    }

    // —— 浏览器内：HTML（live preview）——
    _runBrowserHTML(code, out, btn) {
      out.hidden = false;
      out.innerHTML = '<div class="out-head">预览（浏览器沙箱 iframe）</div>';
      var frame = document.createElement("iframe");
      frame.className = "mdr-run-iframe";
      frame.setAttribute("sandbox", "allow-scripts");
      frame.srcdoc = code;
      out.appendChild(frame);
      if (btn) btn.disabled = false;
    }

    // —— 浏览器内：CSS（注入示例 DOM 预览）——
    _runBrowserCSS(code, out, btn) {
      out.hidden = false;
      var demo = '<div class="d"><h1>标题 H1</h1><h2>标题 H2</h2>' +
        '<p>这是 <strong>加粗</strong> 与 <em>斜体</em> 文本，以及 <a href="#">链接</a>。</p>' +
        '<ul><li>列表项一</li><li>列表项二</li></ul><button>按钮</button>' +
        '<blockquote>引用块</blockquote><pre><code>code sample</code></pre></div>';
      var doc = '<!doctype html><html><head><meta charset="utf-8"><style>' +
        code + '</style></head><body>' + demo + '</body></html>';
      out.innerHTML = '<div class="out-head">CSS 预览（浏览器沙箱 iframe）</div>';
      var frame = document.createElement("iframe");
      frame.className = "mdr-run-iframe";
      frame.setAttribute("sandbox", "allow-scripts");
      frame.srcdoc = doc;
      out.appendChild(frame);
      if (btn) btn.disabled = false;
    }

    // —— 服务端语言（python / node / bash）：经 sandbox 属性指向的后端端点执行 ——
    async _runServer(norm, code, out, btn) {
      var ep = this.getAttribute("sandbox");
      if (!ep) {
        out.hidden = false;
        out.innerHTML = '<div class="out-head">提示</div>' +
          '<div class="notice">未配置沙箱后端。请在 &lt;md-renderer&gt; / &lt;ai-message&gt; 上设置 ' +
          '<code>sandbox="/api/run"</code> 属性以执行 ' + norm + ' 代码。</div>';
        return;
      }
      if (btn) { btn.disabled = true; btn.textContent = "运行中…"; }
      out.hidden = false;
      out.innerHTML = '<div class="out-head">运行 ' + norm + '（后端沙箱）</div><pre>执行中…</pre>';
      var pre = out.querySelector("pre");
      try {
        var r = await fetch(ep, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ lang: norm, code: code })
        });
        var d = await r.json();
        var lines = [];
        if (d.output) lines.push(d.output);
        if (d.error) lines.push(d.error);
        pre.className = (d.error && !d.output) ? "err" : "";
        pre.textContent = (lines.join("\n") || "(无输出)") +
          (d.exitCode != null ? ("\n\n[exit " + d.exitCode + "]") : "");
      } catch (e) {
        pre.className = "err";
        pre.textContent = "请求失败：" + e.message;
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "▶ 运行"; }
      }
    }

    _updateStatus() {
      var reg = (window.hljs && hljs.listLanguages) ? hljs.listLanguages().length : 0;
      var failed = this._failed.size;
      var ok = reg - 0; // 已注册即视作可用
      var hit = "--", full = false, distinct = 0;
      if (window.EmojiLoader) {
        var es = EmojiLoader.getStats();
        hit = (es.hitRate * 100).toFixed(0) + "%";
        full = EmojiLoader.isLoaded();
        distinct = es.distinct;
      }
      var parts = [];
      parts.push("语言包注册 <b class='" + (reg ? "ok" : "warn") + "'>" + reg + "</b>");
      if (failed) parts.push("未就绪 <b class='err'>" + failed + "</b>");
      parts.push("emoji 命中 <b class='ok'>" + hit + "</b>");
      parts.push("全量 <b class='" + (full ? "ok" : "warn") + "'>" + (full ? "是" : "否") + "</b>");
      if (this._updatedAt) {
        var t = new Date(this._updatedAt * 1000);
        parts.push("更新 " + t.toLocaleTimeString());
      }
      this._status.innerHTML = parts.join(" · ");
      this._emitStatus(parts.join(" · ").replace(/<[^>]+>/g, ""));
    }
    _setStatusError(msg) {
      this._status.innerHTML = "<b class='err'>" + escapeHtml(msg) + "</b>";
      this._emitStatus(msg);
    }
    _emitStatus(text) {
      try {
        this.dispatchEvent(new CustomEvent("mdr-status", { detail: text, bubbles: true }));
      } catch (e) {}
    }
  }

  if (!customElements.get("md-renderer")) {
    customElements.define("md-renderer", MdRenderer);
  }
})();
