/**
 * Markdown 渲染器
 * ===============
 *
 * Renderer 抽象基类的具体实现之一。
 * 将来的 TypstRenderer / LatexRenderer 与本文件是平行关系，
 * 只需各自实现 ensureDeps + parse，即可被 registry 统一分发。
 *
 * 本渲染器保留的能力：
 *   - marked 解析 → DOMPurify 消毒 → highlight.js 高亮
 *   - 语言按需加载（LangLoader + lang-bundle）
 *   - emoji 二级加载（emoji-common + emoji-full）+ :shortcode: 扩展
 *   - 国旗 polyfill（Twemoji 兜底）
 *   - 代码块语言标题栏 + 行号（由基类 decorateBlocks 提供）
 *
 * 已移除：代码运行沙箱（原版功能，本产品不要）
 */
(function () {
  "use strict";

  // ===== highlight.js 主题（内联，按 :host([theme]) 双色适配）=====
  // 注意：两个主题必须各自包成独立的 :host([theme='x']){...} 块。
  // 若写成逐条加前缀的同权重规则，特异性相同会互相污染（实测 light 取到 dark 值）。
  const HLJS_BASE = [
    "pre code.hljs{display:block;overflow-x:auto;padding:1em}",
    "code.hljs{padding:3px 5px}"
  ];
  const HLJS_DARK = [
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
  const HLJS_LIGHT = [
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
  const HLJS_THEME =
    ":host([theme='dark']){" + HLJS_BASE.join("") + HLJS_DARK.join("") + "}"
    + ":host([theme='light']){" + HLJS_BASE.join("") + HLJS_LIGHT.join("") + "}";

  // ===== Markdown 内容排版样式（基类只给骨架，细节在此）=====
  const MD_CSS = [
    ".rnd-content h1,.rnd-content h2,.rnd-content h3,.rnd-content h4{line-height:1.3;margin:1.1em 0 .5em;font-weight:600}",
    ".rnd-content h1{font-size:1.7em;border-bottom:1px solid var(--rnd-border);padding-bottom:.3em}",
    ".rnd-content h2{font-size:1.4em;border-bottom:1px solid var(--rnd-border);padding-bottom:.3em}",
    ".rnd-content h3{font-size:1.2em}",
    ".rnd-content h4{font-size:1.05em}",
    ".rnd-content p{margin:.6em 0}",
    ".rnd-content a{color:var(--rnd-accent);text-decoration:none}",
    ".rnd-content a:hover{text-decoration:underline}",
    ".rnd-content code{background:var(--rnd-code-bg);padding:.15em .4em;border-radius:5px;font-size:.88em;",
    "  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}",
    ".rnd-content pre{background:var(--rnd-code-bg);border:1px solid var(--rnd-border);border-radius:8px;margin:.7em 0;overflow:auto}",
    ".rnd-content pre code{background:none;padding:0;font-size:.88em;line-height:1.6}",
    ".rnd-content blockquote{margin:.6em 0;padding:0 1em;color:var(--rnd-muted);border-left:4px solid var(--rnd-border)}",
    ".rnd-content table{border-collapse:collapse;margin:.6em 0;display:block;overflow:auto;width:max-content;max-width:100%}",
    ".rnd-content th,.rnd-content td{border:1px solid var(--rnd-border);padding:6px 13px}",
    ".rnd-content tr:nth-child(2n){background:rgba(127,127,127,.08)}",
    ".rnd-content img{max-width:100%;border-radius:6px}",
    // 国旗（FlagPolyfill 生成的 <img>）必须**跟着文字大小**，不能像普通图片那样撑满。
    // 之前没有这条规则，img 就按 SVG 固有尺寸 + `max-width:100%` 放大到 1000px+，
    // 视觉上"跟图片一样大"。这里钉死为 1em 并在基线上对齐，与 emoji 完全一致。
    ".rnd-content img.emoji-flag{width:1em;height:1em;max-width:none;border-radius:0;",
    "  display:inline-block;vertical-align:-0.12em;margin:0 .04em;object-fit:contain}",
    ".rnd-content ul,.rnd-content ol{padding-left:2em;margin:.5em 0}",
    ".rnd-content hr{border:none;border-top:1px solid var(--rnd-border);margin:1.4em 0}",
    ".rnd-content input[type=checkbox]{margin-right:.4em}"
  ].join("");

  // ===== 数学公式（KaTeX）=====
  // KaTeX 自带样式已在 html 模式、无需按主题重渲染；这里只做壳层微调。
  const MATH_CSS = [
    ".rnd-math-display{display:block;margin:1em 0;overflow-x:auto;overflow-y:hidden;text-align:center}",
    ".rnd-math-display .katex-display{margin:0}",
    ".rnd-math-inline{display:inline}",
    // KaTeX 的公式默认继承正文字号，这里压一点让它与行高更协调
    ".rnd-content .katex{font-size:1.05em}",
    ".rnd-math-error{border-bottom:1px dashed #ff6b6b;color:#ff6b6b;",
    "  font-family:ui-monospace,Consolas,monospace;font-size:.9em;cursor:help}"
  ].join("");

  // ===== 图表（Mermaid）=====
  const MMD_CSS = [
    ".rnd-mmd{background:var(--rnd-panel-2);border:1px solid var(--rnd-border);border-radius:8px;",
    "  margin:.8em 0;padding:14px;text-align:center;overflow:auto}",
    // 未渲染完成时，源码以等宽小字占位，避免高度跳变太突兀
    ".rnd-mmd:not([data-mmd-ready]){color:var(--rnd-muted);font-size:.85em;",
    "  font-family:ui-monospace,Consolas,monospace;text-align:left;white-space:pre-wrap}",
    ".rnd-mmd svg{max-width:100%;height:auto;display:inline-block}",
    ".rnd-mmd-error{border-color:#ff6b6b;background:rgba(255,107,107,.08);text-align:left}",
    ".rnd-mmd-msg{color:#ff6b6b;font-weight:600;font-size:0.9286rem;margin-bottom:6px}",
    ".rnd-mmd-src{margin:0;padding:0;background:none;border:none;color:var(--rnd-muted);",
    "  font-family:ui-monospace,Consolas,monospace;font-size:0.8571rem;line-height:1.5;",
    "  white-space:pre-wrap;word-break:break-word}"
  ].join("");

  const Base = window.RendererABC;
  if (!Base) {
    console.error("[MarkdownRenderer] 未找到 RendererABC，请先加载 core/renderers/base.js");
    return;
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // =====================================================================
  // 运行时垫片：LangLoader（按需语言）+ EmojiLoader（二级 emoji）
  // 属于 markdown 渲染器专属依赖，故放在本文件；typst 渲染器不需要。
  // =====================================================================
  function ensureShim() {
    if (window.__rndShimInstalled) return;
    window.__rndShimInstalled = true;

    if (window.hljs) {
      const sessionLoaded = Object.create(null);
      let readyHandler = null;
      const IDLE_MS = 3 * 60 * 60 * 1000;
      let idleTimer = null;
      const isRegistered = (n) => !!(window.hljs && window.hljs.getLanguage && window.hljs.getLanguage(n));
      const resolve = (raw) => {
        if (!raw) return null;
        let n = String(raw).toLowerCase();
        if (window.HLJS_ALIASES && window.HLJS_ALIASES[n]) n = window.HLJS_ALIASES[n];
        return n;
      };
      const fireReady = (n, ok) => { if (readyHandler) { try { readyHandler(n, ok); } catch (e) {} } };
      const resetIdle = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => { for (const k in sessionLoaded) delete sessionLoaded[k]; }, IDLE_MS);
      };
      let bundleLoading = null;
      const ensureBundle = () => {
        if (bundleLoading) return bundleLoading;
        bundleLoading = new Promise((res) => {
          const s = document.createElement("script");
          s.src = "vendor/lang-bundle.js";
          s.onload = () => res(true);
          s.onerror = () => res(false);
          document.head.appendChild(s);
        });
        return bundleLoading;
      };
      // 单文件语言包（vendor/lang/<name>.min.js）——bundle 未覆盖的语言走这里
      const onceLoad = (name) => new Promise((res) => {
        const s = document.createElement("script");
        s.src = "vendor/lang/" + name + ".min.js";
        s.onload = () => res(true);
        s.onerror = () => res(false);
        document.head.appendChild(s);
      });
      /**
       * 确保某语言已注册。
       * 顺序：已注册 → 直接用；否则先试单文件，再试 bundle。
       * （原版还有 CDN 回退，这里去掉 —— 纯前端产品不依赖外网 CDN）
       */
      const ensure = async (name) => {
        if (isRegistered(name)) { sessionLoaded[name] = true; resetIdle(); return true; }
        let ok = await onceLoad(name);
        ok = !!(ok && isRegistered(name));
        if (!ok) {
          const bundleOk = await ensureBundle();
          ok = !!(bundleOk && isRegistered(name));
        }
        sessionLoaded[name] = ok;
        fireReady(name, ok);
        resetIdle();
        return ok;
      };
      window.LangLoader = {
        resolve, isRegistered, ensure,
        isBundleLoading: () => !!bundleLoading,
        preload() {}, init: () => Promise.resolve(),
        setReadyHandler(fn) { readyHandler = fn; },
      };
    }

    (function () {
      const FULL_URL = "vendor/emoji-full.js";
      let loaded = false, loading = null, readyHandler = null;
      let seenThisRender = new Set();
      const sessionUse = Object.create(null);
      const isCommon = (n) => !!(window.EMOJI_MAP && Object.prototype.hasOwnProperty.call(window.EMOJI_MAP, n));
      const beginRender = () => { seenThisRender = new Set(); };
      const endRender = () => { const s = seenThisRender; seenThisRender = new Set(); return s; };
      const track = (name) => { if (name) sessionUse[name] = (sessionUse[name] || 0) + 1; };
      const note = (name) => {
        if (loaded && window.EMOJI_FULL &&
            !Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, name)) return;
        seenThisRender.add(name);
        ensureFull();
      };
      function ensureFull() {
        if (loaded) return Promise.resolve(true);
        if (loading) return loading;
        loading = new Promise((res) => {
          const sc = document.createElement("script");
          sc.src = FULL_URL;
          sc.onload = () => {
            if (window.EMOJI_FULL && window.EMOJI_MAP) {
              for (const k in window.EMOJI_FULL) {
                if (Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, k))
                  window.EMOJI_MAP[k] = window.EMOJI_FULL[k];
              }
              loaded = true; loading = null; res(true);
              if (readyHandler) readyHandler();
            } else { loading = null; res(false); }
          };
          sc.onerror = () => { loading = null; res(false); };
          document.head.appendChild(sc);
        });
        return loading;
      }
      const getStats = () => {
        let total = 0, distinct = 0, commonDistinct = 0, commonOcc = 0;
        for (const k in sessionUse) {
          if (!Object.prototype.hasOwnProperty.call(sessionUse, k)) continue;
          distinct++; total += sessionUse[k];
          if (isCommon(k)) { commonDistinct++; commonOcc += sessionUse[k]; }
        }
        return {
          total, distinct, commonDistinct, commonOcc,
          hitRate: distinct ? commonDistinct / distinct : 1, fullLoaded: loaded,
        };
      };
      window.EmojiLoader = {
        note, track, beginRender, endRender, ensureFull,
        setReadyHandler(fn) { readyHandler = fn; },
        isLoaded: () => loaded, getStats,
      };
    })();
  }

  // ===== emoji :shortcode: 扩展（仅安装一次）=====
  function ensureEmojiExt() {
    if (window.__rndEmojiExt || !window.marked) return;
    window.__rndEmojiExt = true;
    if (!window.EMOJI_MAP) return;
    try {
      marked.use({
        extensions: [{
          name: "emoji",
          level: "inline",
          start(src) { const i = src.indexOf(":"); return i < 0 ? undefined : i; },
          tokenizer(src) {
            const m = /^:([a-z0-9_+\-]+):/i.exec(src);
            if (m) {
              const key = m[1].toLowerCase();
              if (Object.prototype.hasOwnProperty.call(window.EMOJI_MAP, key)) {
                if (window.EmojiLoader) EmojiLoader.track(key);
                return { type: "emoji", raw: m[0], text: window.EMOJI_MAP[key] };
              }
              if (window.EmojiLoader) { EmojiLoader.track(key); EmojiLoader.note(key); }
            }
            return undefined;
          },
          renderer(token) { return token.text; },
        }],
      });
    } catch (e) { /* marked 已装过扩展则忽略 */ }
  }

  // =====================================================================
  // 具体渲染器
  // =====================================================================
  class MarkdownRenderer extends Base {
    static get tagName() { return "md-renderer"; }

    static get meta() {
      return {
        id: "markdown",
        title: "Markdown",
        langs: ["markdown", "md", "gfm", "commonmark"],
        deps: [
          "vendor/marked.min.js",
          "vendor/purify.min.js",
          "vendor/highlight.min.js",
          "vendor/lang/aliases.js",
          "vendor/emoji-common.js",
          "vendor/emoji-loader.js",
          "vendor/flag-polyfill.js",
        ],
      };
    }

    extraCSS() {
      // KaTeX 的样式必须内联进 Shadow DOM（外部 <link> 穿不透 shadow 边界），
      // 由 MathEnhancer 在加载完 CSS 后提供；未就绪时为空串。
      const katexCss = (window.MathEnhancer && MathEnhancer.getCSS)
        ? MathEnhancer.getCSS() : "";
      // markmap 同理：它的 globalCSS + 壳层样式也必须在 shadow root 里才生效
      const mmapCss = (window.MarkmapEnhancer && MarkmapEnhancer.getCSS)
        ? MarkmapEnhancer.getCSS() : "";
      return HLJS_THEME + MD_CSS + MATH_CSS + MMD_CSS + katexCss + mmapCss;
    }

    /** 抽象实现①：确保运行时依赖已就绪 */
    async ensureDeps() {
      ensureShim();
      ensureEmojiExt();

      // 语言包 / emoji 全量异步就绪后，重渲染所有实例
      if (window.LangLoader) LangLoader.setReadyHandler(() => Base.rerenderAll());
      if (window.EmojiLoader) EmojiLoader.setReadyHandler(() => Base.rerenderAll());

      if (!window.marked) throw new Error("marked 未加载");

      // 公式与图表的依赖不阻塞首屏：
      // 它们体积大（mermaid 2.5MB），先让 markdown 正常出内容，
      // 依赖到了再重渲染一次，公式会从源码变成排版后的公式。
      this._loadEnhancerDeps();

      return { marked: window.marked, DOMPurify: window.DOMPurify, hljs: window.hljs };
    }

    /** 异步补齐 KaTeX / Mermaid / markmap，就绪后重渲染所有实例 */
    _loadEnhancerDeps() {
      const needMath = window.MathEnhancer && !MathEnhancer.hasDeps();
      const needMmd = window.MermaidEnhancer && !MermaidEnhancer.hasDeps();
      const needMap = window.MarkmapEnhancer && !MarkmapEnhancer.hasDeps();
      if (!needMath && !needMmd && !needMap) return;
      if (this.__enhancerPending) return;
      this.__enhancerPending = true;

      const tasks = [];
      if (needMath) tasks.push(MathEnhancer.ensure());
      if (needMmd) tasks.push(MermaidEnhancer.ready());
      if (needMap) tasks.push(MarkmapEnhancer.ensure());

      Promise.all(tasks).then(() => {
        this.__enhancerPending = false;
        // KaTeX 样式是**后到的**，必须重新合成 shadow root 里的样式表，
        // 否则公式 HTML 有了、排版却是纯文本。
        // 遍历所有实例统一刷新（每个实例各有一份 shadow 样式）。
        Base.INSTANCES.forEach((inst) => {
          try {
            if (inst._styleEl) inst._styleEl.textContent = inst._composeCSS();
          } catch (e) {}
        });
        // 公式是在 parse 阶段同步处理的，所以重渲染才会生效
        Base.rerenderAll();
      }).catch(() => {
        this.__enhancerPending = false;
      });
    }

    /** 抽象实现②：markdown → HTML */
    parse(text) {
      let html = "";
      try {
        html = window.marked ? marked.parse(text || "") : (text || "");
      } catch (e) {
        html = Base.escapeHtml(text || "");
      }

      // 图表块先换成带 data-mmd-id 的容器（必须在消毒之前完成，
      // 这样 DOMPurify 会连容器一起检查，顺带把里面的源码清干净）
      html = this._extractDiagrams(html);
      // 脑图块同理（```markmap）
      html = this._extractMindmaps(html);

      if (window.DOMPurify) {
        html = DOMPurify.sanitize(html, {
          ADD_ATTR: ["target", "data-mmd-id", "data-mm-id"],
          // Mermaid 渲染出的 SVG 会用到下列属性；留出白名单，
          // 否则第二次渲染（主题切换后）会被消毒掉。
          ADD_TAGS: ["foreignObject"],
        });
      }

      // 公式在消毒之后处理：KaTeX 的输出是可信的本地产物，
      // 放在这一步可以避免它的复杂 HTML/MathML 被 DOMPurify 削掉。
      // 做法是「占位符 → 消毒 → 再回填」，见 math.js 的说明。
      // 依赖未就绪时 preprocess 会原样返回，公式暂以源码显示，
      // 等 _loadEnhancerDeps 完成后的重渲染再变成公式。
      this._mathStore = null;
      this._mathStats = null;
      if (window.MathEnhancer) {
        const math = MathEnhancer.preprocess(html);
        if (!math.skipped) {
          this._mathStore = math.store;
          this._mathStats = math.stats;
        }
        html = math.html;
      }

      return html;
    }

    /** 把 ```mermaid 代码块换成图表容器 */
    _extractDiagrams(html) {
      // marked 输出形如：<pre><code class="language-mermaid">...</code></pre>
      return html.replace(
        /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,
        (m, inner) => {
          const code = inner
            .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
            .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
            .replace(/&amp;/g, "&");
          return '<div class="rnd-mmd" data-mmd-id="' + (this._nextMmdId()) + '">'
            + escHtml(code) + "</div>";
        }
      );
    }

    /**
     * 分配一个图表容器 id。
     * 用普通方法而不是带 getter 的属性：增量赋值（`this._x++`）需要 setter，
     * 只写 getter 会在严格模式下抛 "which has only a getter"。
     */
    _nextMmdId() {
      if (this.__mmdSeq == null) this.__mmdSeq = 0;
      return this.__mmdSeq++;
    }

    /**
     * 把 ```markmap 代码块换成脑图容器。
     *
     * markmap 吃的是 **Markdown 源码**（它自己解析标题层级），
     * 所以这里必须把 marked 转义过的实体还原回原始 Markdown ——
     * 与 _extractDiagrams 同理，但要注意 markmap 需要 `#`、`-` 这些原字符。
     */
    _extractMindmaps(html) {
      return html.replace(
        /<pre><code class="language-markmap">([\s\S]*?)<\/code><\/pre>/g,
        (m, inner) => {
          const code = inner
            .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
            .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
            .replace(/&amp;/g, "&");
          return '<div class="rnd-mm" data-mm-id="' + (this._nextMmdId()) + '">'
            + escHtml(code) + "</div>";
        }
      );
    }

    /** 后处理：公式回填 → 图表排队 → 国旗兜底 → 语法高亮 */
    postProcess(host) {
      // 1) 回填 KaTeX（占位符在文本节点里，得走 DOM 替换）
      if (window.MathEnhancer && this._mathStore) {
        try { MathEnhancer.unstash(host, this._mathStore); } catch (e) {}
        this._mathStore = null;
      }
      // 2) 图表：异步渲染，自己管理重建
      if (window.MermaidEnhancer) {
        this._bindMmdSettle();
        try { MermaidEnhancer.schedule(host); } catch (e) {}
      }
      // 2b) 脑图（markmap）：同样是异步渲染
      if (window.MarkmapEnhancer) {
        this._bindMmSettle();
        try { MarkmapEnhancer.schedule(host); } catch (e) {}
      }
      if (window.FlagPolyfill) {
        try { FlagPolyfill.process(host); } catch (e) {}
      }
      this._highlight(host);
    }

    /** 公式块 / 图表块 / 脑图块不再是「代码」，跳过基类的语言标题栏 + 行号 */
    shouldDecorateBlock(pre, lang) {
      if (lang === "mermaid") return false;
      if (lang === "markmap") return false;
      if (pre.closest && pre.closest(".rnd-math")) return false;
      return true;
    }

    /**
     * 主题切换：公式靠 CSS 变量自动换色，不必重渲染；
     * 但 Mermaid 把颜色写死在 SVG 里了，必须重画一遍。
     * markmap 走 CSS 变量 + .markmap-dark 类，**不需要重渲染**。
     */
    onThemeChange() {
      if (!this._content) return;
      if (window.MermaidEnhancer) {
        try { MermaidEnhancer.invalidate(this._content); } catch (e) {}
      }
      if (window.MarkmapEnhancer) {
        try { MarkmapEnhancer.invalidate(this._content); } catch (e) {}
      }
      this._updateStatus();
    }

    /** 脑图渲染完成（异步）后刷新状态栏 */
    _bindMmSettle() {
      if (this.__mmSettleBound) return;
      this.__mmSettleBound = true;
      this.shadowRoot.addEventListener("rnd-mm-settled", () => {
        this._updateStatus();
      });
    }

    /** 图表渲染完成（异步）后刷新状态栏，否则会一直停在 0/2 */
    _bindMmdSettle() {
      if (this.__mmdSettleBound) return;
      this.__mmdSettleBound = true;
      // 监听在 shadow root 上：事件从 _content 冒泡上来
      this.shadowRoot.addEventListener("rnd-mmd-settled", () => {
        this._updateStatus();
      });
    }

    /** 语言按需加载：未注册语言触发 LangLoader.ensure，就绪后 rerenderAll */
    _highlight(host) {
      if (!window.hljs) return;
      // 依赖未就绪时直接跳过。
      // connectedCallback 里 setAttribute('theme') 会同步触发一次 _render()，
      // 那一刻 ensureDeps() 尚未完成、LangLoader 还不存在 —— 若此时把语言
      // 记入 _failedLangs，等依赖真正就绪后也会被跳过，语言永远加载不上。
      if (!window.LangLoader) return;

      host.querySelectorAll("pre code").forEach((code) => {
        const m = (code.className || "").match(/language-([\w+#.\-]+)/);
        const raw = m ? m[1] : null;
        const lang = raw ? LangLoader.resolve(raw) : null;

        if (!lang || lang === "plaintext" || lang === "plain") {
          try { hljs.highlightElement(code); } catch (e) {}
          return;
        }
        if (LangLoader.isRegistered(lang)) {
          try { hljs.highlightElement(code); } catch (e) {}
          return;
        }
        if (this._failedLangs.has(lang) || this._unavailableLangs.has(lang)) return;
        this._failedLangs.add(lang);
        LangLoader.ensure(lang).then((ok) => {
          // 成功或失败都要从「加载中」移除；失败的语言不再重试
          this._failedLangs.delete(lang);
          if (!ok) this._unavailableLangs.add(lang);
          this._updateStatus();
        });
      });
    }

    /** 状态栏片段 */
    statusItems() {
      const reg = (window.hljs && hljs.listLanguages) ? hljs.listLanguages().length : 0;
      const items = [{ label: "语言包注册", value: reg, tone: reg ? "ok" : "warn" }];
      const pending = this._failedLangs.size;
      if (pending) items.push({ label: "加载中", value: pending, tone: "warn" });
      const bad = this._unavailableLangs.size;
      if (bad) items.push({ label: "不可用", value: bad, tone: "err" });
      if (window.EmojiLoader) {
        const es = EmojiLoader.getStats();
        items.push({ label: "emoji 命中", value: (es.hitRate * 100).toFixed(0) + "%", tone: "ok" });
        items.push({ label: "全量", value: EmojiLoader.isLoaded() ? "是" : "否", tone: EmojiLoader.isLoaded() ? "ok" : "warn" });
      }

      // 公式：统计本篇渲染了多少个
      if (this._mathStats && (this._mathStats.display || this._mathStats.inline)) {
        const n = this._mathStats.display + this._mathStats.inline;
        items.push({ label: "公式", value: n, tone: "ok" });
        if (this._mathStats.failed) {
          items.push({ label: "公式错误", value: this._mathStats.failed, tone: "err" });
        }
      }

      // 图表：已渲染 / 总数，或失败数
      if (window.MermaidEnhancer && this._content) {
        const ms = MermaidEnhancer.stats(this._content);
        if (ms.total) {
          if (ms.failed) {
            items.push({ label: "图表失败", value: ms.failed, tone: "err" });
          } else {
            items.push({
              label: "图表",
              value: ms.done + "/" + ms.total,
              tone: ms.done === ms.total ? "ok" : "warn",
            });
          }
        }
      }

      // 脑图：已渲染 / 总数，或失败数
      if (window.MarkmapEnhancer && this._content) {
        const ms = MarkmapEnhancer.stats(this._content);
        if (ms.total) {
          if (ms.failed) {
            items.push({ label: "脑图失败", value: ms.failed, tone: "err" });
          } else {
            items.push({
              label: "脑图",
              value: ms.done + "/" + ms.total,
              tone: ms.done === ms.total ? "ok" : "warn",
            });
          }
        }
      }
      return items;
    }
  }

  // 实例级状态：每个实例独立记录「加载中」与「不可用」的语言
  Object.defineProperty(MarkdownRenderer.prototype, "_failedLangs", {
    get() {
      if (!this.__failedLangs) this.__failedLangs = new Set();
      return this.__failedLangs;
    },
    configurable: true,
  });
  Object.defineProperty(MarkdownRenderer.prototype, "_unavailableLangs", {
    get() {
      if (!this.__unavailableLangs) this.__unavailableLangs = new Set();
      return this.__unavailableLangs;
    },
    configurable: true,
  });

  Base.register(MarkdownRenderer);
  window.MarkdownRenderer = MarkdownRenderer;
})();
