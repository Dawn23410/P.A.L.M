/**
 * 渲染器抽象基类（ABC）
 * =====================
 *
 * 设计目标：把「渲染一种标记语言」这件事抽象成一个可替换的能力，
 * 让 md-renderer / 将来的 typst-renderer / latex-renderer 都能平行实现。
 *
 * 这是一个 Web Component（自定义元素），子类只需实现 4 个抽象方法：
 *
 *   static get tagName()        自定义元素标签名，如 'md-renderer'
 *   static get meta()           元信息：{ id, title, langs[], deps[] }
 *   async ensureDeps()          加载本渲染器所需的运行时依赖
 *   parse(text)                 把源码转成 HTML 字符串（核心）
 *
 * 可选覆写（有默认实现）：
 *
 *   postProcess(host)           解析后处理：高亮 / 公式 / 图表 / emoji …
 *   decorateBlocks(host)        代码块装饰：语言标题栏 / 行号 / 运行按钮
 *   extraCSS()                  追加样式
 *   isEmpty(text)               空内容判定
 *   onDepsReady()               依赖就绪后的回调
 *
 * 继承基类即自动获得（模板方法，子类不用重写）：
 *
 *   - Shadow DOM 样式隔离 + 明暗主题（CSS 变量 --rnd-*）
 *   - 状态栏（可关）
 *   - endpoint 轮询拉取
 *   - markdown / source / setContent(el) / refresh() 公共 API
 *   - 依赖就绪后统一重渲染（语言包、emoji 全量等异步加载完成时）
 *
 * 约定：子类不写 constructor 时，基类会负责建好 shadow 骨架。
 *       若子类必须写，务必调用 super()。
 */
import { log } from '../log.js';

(function () {
  "use strict";

  // ===== 全局实例注册表：依赖异步就绪后统一重渲染 =====
  const INSTANCES = new Set();
  function rerenderAll() {
    INSTANCES.forEach((inst) => {
      try { inst._render(); } catch (e) { /* 单个实例失败不影响其他 */ }
      try { inst._updateStatus(); } catch (e) {}
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  /**
   * 抽象方法守卫。JS 没有原生 abstract，用运行时检查模拟：
   * 子类没实现就在实例化/调用时立刻报错，而不是静默行为异常。
   */
  function requireImpl(inst, method) {
    const fn = inst[method];
    if (typeof fn !== "function") {
      throw new Error(
        `[Renderer] ${inst.constructor.name} 必须实现抽象方法 ${method}()`
      );
    }
    return fn;
  }

  // ===== 基类通用样式（主题变量 + 内容排版骨架）=====
  const BASE_CSS = [
    ":host{display:block;width:100%;height:100%;box-sizing:border-box;",
    "  --rnd-panel:#1b1f2a;--rnd-panel-2:#222736;--rnd-text:#e6e9ef;--rnd-muted:#9aa3b2;",
    "  --rnd-border:#2a3040;--rnd-code-bg:#0d1117;--rnd-accent:#5b8cff;",
    "  --rnd-code-soft:rgba(0,0,0,.28);--rnd-gutter:#5b6677;--rnd-gutter-bg:rgba(0,0,0,.18);}",
    ":host([theme='light']){--rnd-panel:#ffffff;--rnd-panel-2:#f6f8fa;--rnd-text:#1f2328;",
    "  --rnd-muted:#57606a;--rnd-border:#d0d7de;--rnd-code-bg:#f6f8fa;--rnd-accent:#0969da;",
    "  --rnd-code-soft:rgba(27,31,35,.06);--rnd-gutter:#6a737d;--rnd-gutter-bg:rgba(27,31,35,.04);}",
    ":host{color-scheme:dark}",
    ":host([theme='light']){color-scheme:light}",
    ".rnd-root{display:flex;flex-direction:column;height:100%;background:var(--rnd-panel);",
    "  color:var(--rnd-text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,",
    "  'PingFang SC','Microsoft YaHei',sans-serif;font-size:1.0714rem;}",
    ".rnd-content{flex:1;overflow-y:auto;padding:20px 22px;line-height:1.7;}",
    ".rnd-content>:first-child{margin-top:0}",
    ".rnd-empty{color:var(--rnd-muted);font-style:italic;padding:8px 2px}",
    ".rnd-status{flex:none;display:flex;gap:14px;align-items:center;flex-wrap:wrap;",
    "  padding:6px 14px;font-size:0.8571rem;color:var(--rnd-muted);",
    "  background:var(--rnd-panel-2);border-top:1px solid var(--rnd-border);}",
    ".rnd-status b.ok{color:#36d399}.rnd-status b.warn{color:#f0c040}.rnd-status b.err{color:#ff6b6b}",
    /* 代码块：语言标题栏 + 行号（通用装饰，各渲染器复用）*/
    ".code-block{display:flex;flex-direction:column;background:var(--rnd-code-bg);",
    "  border:1px solid var(--rnd-border);border-radius:8px;margin:.7em 0;overflow:hidden}",
    ".code-header{display:flex;align-items:center;gap:8px;",
    "  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;",
    "  font-size:0.8571rem;color:var(--rnd-muted);background:var(--rnd-code-soft);",
    "  border-bottom:1px solid var(--rnd-border);padding:4px 12px;user-select:none}",
    ".code-header .ch-lang{font-weight:600;color:var(--rnd-text)}",
    ".code-header .ch-spacer{flex:1}",
    ".code-body{display:flex;flex-direction:row;min-width:0}",
    ".code-block pre{margin:0;border:none;border-radius:0;flex:1;min-width:0}",
    ".code-block pre code{padding:1em;font-size:.88em;line-height:1.6}",
    ".ln-gutter{flex:none;text-align:right;padding:1em 8px;color:var(--rnd-gutter);",
    "  background:var(--rnd-gutter-bg);",
    "  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em;line-height:1.6;",
    "  user-select:none;white-space:pre;overflow:hidden}",
    /* 通用可插拔节点样式 */
    ".rnd-flag{height:1.1em;width:1.4em;vertical-align:-.15em;margin:0 1px;border-radius:2px;display:inline-block}",
    ".rnd-figure{margin:.8em 0;text-align:center}",
    ".rnd-error{margin:.6em 0;padding:10px 14px;border-radius:8px;font-size:0.9286rem;",
    "  background:rgba(255,107,107,.1);border:1px solid rgba(255,107,107,.35);color:#ff6b6b;",
    "  font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}"
  ].join("");

  class Renderer extends HTMLElement {
    // ---- 抽象契约：子类必须覆写 ----
    static get tagName() { requireImpl(this, "__never__"); }
    static get meta() {
      return { id: this.name || "renderer", title: "", langs: [], deps: [] };
    }

    constructor() {
      super();
      this._src = "";            // 源文本
      this._bound = null;        // 子类注入的语法对象（marked / typst …）
      this._pollTimer = null;
      this._updatedAt = 0;
      this._statusExtra = [];    // 状态栏附加片段

      const root = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      const wrap = document.createElement("div");
      wrap.className = "rnd-root";
      const content = document.createElement("div");
      content.className = "rnd-content";
      const status = document.createElement("div");
      status.className = "rnd-status";
      wrap.appendChild(content);
      wrap.appendChild(status);
      root.appendChild(style);
      root.appendChild(wrap);
      this._styleEl = style;
      this._content = content;
      this._status = status;
    }

    static get observedAttributes() {
      return ["endpoint", "poll", "theme", "placeholder", "nostatus"];
    }

    // ---- 生命周期 ----
    connectedCallback() {
      const self = this;
      this._applyNoStatus();

      // 子类声明的依赖就绪后，回填并重渲染
      Promise.resolve()
        .then(() => this.ensureDeps())
        .then((api) => {
          self._bound = api || null;
          self._styleEl.textContent = this._composeCSS();
          if (typeof self.onDepsReady === "function") {
            try { self.onDepsReady(self._bound); } catch (e) { console.error(e); }
          }
          self._render();
          self._updateStatus();
        })
        .catch((err) => {
          log.error({ source: 'cpu', target: 'fe', type: 'error', payload: `${this.constructor.name} 依赖加载失败: ${err && err.message}` });
          self._setStatusError("依赖加载失败：" + err.message);
        });

      INSTANCES.add(this);
      if (!this.hasAttribute("theme")) this.setAttribute("theme", "dark");
      this._startPolling();
      this._startThemeWatch();
    }

    disconnectedCallback() {
      INSTANCES.delete(this);
      this._stopPolling();
      this._stopThemeWatch();
    }

    attributeChangedCallback(name) {
      if (name === "theme" || name === "placeholder") this._render();
      else if (name === "endpoint" || name === "poll") this._startPolling();
      else if (name === "nostatus") this._applyNoStatus();
    }

    // ---- 样式合成：基类 CSS + 子类 CSS ----
    _composeCSS() {
      const extra = (typeof this.extraCSS === "function" && this.extraCSS()) || "";
      return BASE_CSS + extra;
    }

    // ============================================================
    // 抽象方法（子类必须实现）—— 默认实现直接抛错
    // ============================================================

    /** 加载本渲染器所需依赖，返回给 parse 用的语法对象 */
    async ensureDeps() {
      throw new Error(`[Renderer] ${this.constructor.name} 必须实现 ensureDeps()`);
    }

    /** 核心：源码 → HTML 字符串 */
    parse(/* text */) {
      throw new Error(`[Renderer] ${this.constructor.name} 必须实现 parse()`);
    }

    // ============================================================
    // 可选覆写（有默认实现）
    // ============================================================

    /** 解析后处理：高亮、公式、图表、emoji、国旗……默认什么都不做 */
    postProcess(/* host, api */) {}

    /**
     * 是否要装饰这个代码块。
     * 子类可覆写以跳过特定块 —— 典型场景是「数学块 / 图表块」：
     * 它们虽然也是 <pre>，但已经被渲染成公式或图形，再加语言标题栏
     * 和行号就错了。
     */
    shouldDecorateBlock(/* pre, lang */) { return true; }

    /** 代码块装饰：默认给所有 pre 加语言标题栏 + 行号 */
    decorateBlocks(host) {
      host.querySelectorAll("pre").forEach((pre) => {
        if (pre.parentNode && pre.parentNode.classList &&
            pre.parentNode.classList.contains("code-block")) return;
        const code = pre.querySelector("code");
        if (!code) return;

        const text = code.textContent || "";
        const lines = text.replace(/\n+$/, "").split("\n");
        const m = (code.className || "").match(/language-([\w+#.\-]+)/);
        const raw = m ? m[1] : null;

        if (!this.shouldDecorateBlock(pre, raw)) return;

        const block = document.createElement("div");
        block.className = "code-block";

        if (raw) {
          const header = document.createElement("div");
          header.className = "code-header";
          const langSpan = document.createElement("span");
          langSpan.className = "ch-lang";
          langSpan.textContent = "# " + raw;
          header.appendChild(langSpan);
          const spacer = document.createElement("span");
          spacer.className = "ch-spacer";
          header.appendChild(spacer);
          // 子类可在此插入额外按钮（运行 / 渲染 / 复制…）
          if (typeof this.augmentCodeHeader === "function") {
            this.augmentCodeHeader(header, { lang: raw, code, block });
          }
          block.appendChild(header);
        }

        const body = document.createElement("div");
        body.className = "code-body";
        if (lines.length > 1) {
          const gutter = document.createElement("div");
          gutter.className = "ln-gutter";
          gutter.textContent = lines.map((_, i) => i + 1).join("\n");
          body.appendChild(gutter);
        }

        pre.parentNode.insertBefore(block, pre);
        block.appendChild(body);
        body.appendChild(pre);
      });
    }

    /** 空内容判定 */
    isEmpty(text) {
      return !String(text || "").trim();
    }

    /** 追加样式 */
    extraCSS() { return ""; }

    // ============================================================
    // 模板方法：固定的渲染流程，子类不重写
    // ============================================================

    _render() {
      const text = this._src || "";

      if (this.isEmpty(text)) {
        const ph = this.getAttribute("placeholder") || "等待内容输入…";
        this._content.innerHTML = '<div class="rnd-empty">' + escapeHtml(ph) + "</div>";
        this._afterRender();
        return;
      }

      let html;
      try {
        html = this.parse(text, this._bound);
      } catch (err) {
        // 解析失败：不炸整个页面，就地展示错误
        this._content.innerHTML =
          '<div class="rnd-error">渲染失败：\n' + escapeHtml(err.message || String(err)) + "</div>";
        return;
      }

      this._content.innerHTML = html == null ? "" : html;
      this._afterRender();
    }

    /** 解析后的统一后处理链：子类钩子 → 装饰 → 子类清理 */
    _afterRender() {
      const host = this._content;
      try { this.postProcess(host, this._bound); } catch (e) { console.error("[Renderer] postProcess:", e); }
      try { this.decorateBlocks(host); } catch (e) { console.error("[Renderer] decorateBlocks:", e); }
      if (typeof this.afterRender === "function") {
        try { this.afterRender(host, this._bound); } catch (e) { console.error("[Renderer] afterRender:", e); }
      }
    }

    // ---- 状态栏 ----
    _applyNoStatus() {
      if (!this._status) return;
      this._status.style.display = this.hasAttribute("nostatus") ? "none" : "";
    }

    /** 子类提供状态片段：返回 [{label, value, tone}] */
    statusItems(/* api */) { return []; }

    _updateStatus() {
      const parts = [];
      try {
        const items = this.statusItems(this._bound) || [];
        items.forEach((it) => {
          const tone = it.tone ? ` class='${it.tone}'` : "";
          parts.push(`${it.label} <b${tone}>${escapeHtml(String(it.value))}</b>`);
        });
      } catch (e) { /* 忽略子类状态异常 */ }

      if (this._updatedAt) {
        parts.push("更新 " + new Date(this._updatedAt * 1000).toLocaleTimeString());
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
        this.dispatchEvent(new CustomEvent("rnd-status", { detail: text, bubbles: true }));
      } catch (e) {}
    }

    // ---- endpoint 轮询 ----
    async refresh() {
      const ep = this.getAttribute("endpoint");
      if (!ep) { this._render(); return; }
      try {
        const r = await fetch(ep, { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const ct = r.headers.get("content-type") || "";
        let text;
        if (ct.indexOf("application/json") >= 0) {
          const d = await r.json();
          text = d.markdown != null ? d.markdown
               : d.content != null ? d.content
               : d.source != null ? d.source : "";
          this._updatedAt = d.updated_at || 0;
        } else {
          text = await r.text();
        }
        this._src = text || "";
        this._render();
        this._updateStatus();
      } catch (e) {
        this._setStatusError("拉取失败：" + e.message);
      }
    }

    _startPolling() {
      this._stopPolling();
      const ep = this.getAttribute("endpoint");
      const poll = parseInt(this.getAttribute("poll") || "2000", 10);
      if (!ep || !poll || poll <= 0) return;
      this.refresh();
      this._pollTimer = setInterval(() => this.refresh(), poll);
    }
    _stopPolling() {
      if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
    }

    // ---- 主题变化：需要整篇重渲染的产物（如 Mermaid 图）在这里挂钩 ----
    // 大多数内容靠 CSS 变量自动换色，不需要重渲染；
    // 但把颜色固化进 DOM 的产物（SVG）必须重画。
    // 全局主题系统切换 <html data-theme> 时会派发 rnd-theme-change 事件。
    _startThemeWatch() {
      if (this._themeWatch) return;
      this._themeWatch = () => {
        try { this.onThemeChange(); } catch (e) { console.error("[Renderer] onThemeChange:", e); }
      };
      window.addEventListener("rnd-theme-change", this._themeWatch);
    }
    _stopThemeWatch() {
      if (this._themeWatch) {
        window.removeEventListener("rnd-theme-change", this._themeWatch);
        this._themeWatch = null;
      }
    }

    /** 可选覆写：主题切换时的额外处理（默认什么都不做）*/
    onThemeChange() {}

    // ---- 公共 API ----
    /** 主入口：设内容（语义由渲染器决定，md 是 markdown，typst 是 typst 源码）*/
    setContent(v) { this._src = v == null ? "" : String(v); this._render(); this._updateStatus(); }
    get content() { return this._src; }

    /** 兼容别名：markdown 渲染器习惯用这个 */
    set markdown(v) { this.setContent(v); }
    get markdown() { return this._src; }
    setMarkdown(v) { this.setContent(v); }
    /** 通用别名 */
    set source(v) { this.setContent(v); }
    get source() { return this._src; }

    /** 手动重渲染（依赖异步就绪、外部状态变化时用）*/
    redraw() { this._render(); this._updateStatus(); }

    get theme() { return this.getAttribute("theme") || "dark"; }
    set theme(v) {
      const t = (v === "light") ? "light" : "dark";
      if (this.getAttribute("theme") !== t) this.setAttribute("theme", t);
    }
  }

  // ===== 派生工具：给子类用 =====
  Renderer.escapeHtml = escapeHtml;
  Renderer.rerenderAll = rerenderAll;
  Renderer.INSTANCES = INSTANCES;

  /**
   * 注册一个渲染器子类（幂等）。
   *
   * 做两件事：
   *   1. customElements.define(tagName, Sub) —— 让标签可用
   *   2. 登记到 registry（按语言分发）—— 让 UI 能查「谁支持某语言」
   *
   * 第 2 步是必须的：注册表与基类是两个模块，若只做第 1 步，
   * 会出现「元素注册成功但注册表查不到」的怪象。
   * 由于 base.js 不能静态 import registry.js（会形成循环依赖），
   * 这里用注入方式：index.js 在加载 base 后调用 Renderer.useRegistry()。
   */
  let registryApi = null;
  Renderer.useRegistry = function useRegistry(api) {
    registryApi = api;
  };

  Renderer.register = function register(Sub) {
    const tag = Sub.tagName;
    if (!tag) throw new Error("[Renderer] 子类必须定义 static get tagName()");
    if (!customElements.get(tag)) customElements.define(tag, Sub);
    if (registryApi && typeof registryApi.register === "function") {
      registryApi.register(Sub);
    }
    return Sub;
  };

  window.RendererABC = Renderer;
})();
