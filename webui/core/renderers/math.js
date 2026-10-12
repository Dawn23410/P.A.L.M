/**
 * 数学公式渲染（KaTeX）
 * =====================
 *
 * 这是一个「增强模块」，不是独立渲染器 —— 它挂在 markdown 渲染器的
 * postProcess 钩子上，负责把正文里的公式源码变成排版后的公式。
 *
 * 为什么不做成独立渲染器：
 *   公式是嵌在 markdown 正文里的片段，而渲染器是整篇的接管者。
 *   如果硬做成 `math-renderer`，一篇文档就只能「要么全是公式、要么全不是」。
 *   图表（mermaid）同理。
 *
 * 支持的定界符：
 *   行间  $$…$$           独立成段，居中
 *   行内  $…$             随文字走
 *
 * 关于 \(…\) ：
 *   本模块保留了识别逻辑，但在 marked 管线里**它实际不会生效** ——
 *   marked 会先把反斜杠转义吃掉（`\(` → `(`），等我们拿到 HTML 时
 *   定界符已经不存在了。要在 marked 下用它，必须写自定义 tokenizer 扩展
 *   （与 emoji 扩展同理），代价与收益不成比例。
 *   **建议统一用 $…$ 与 $$…$$**，这两个定界符在 markdown 里也更通用。
 *
 * 不做的事：
 *   - 行内识别 `$` 与数字混排的场景（会把「$5」误判成公式开头），
 *     规则见 RE_INLINE_DOLLAR 的说明
 */
(function () {
  "use strict";

  const CSS_URL = "vendor/katex/katex.min.css";
  const JS_URL = "vendor/katex/katex.min.js";

  // ---- 定界符 ----
  // 行间：$$…$$（可跨行）
  const RE_DISPLAY = /\$\$([\s\S]+?)\$\$/g;
  // 行内：\(…\)（明确，无歧义）—— 仅对「非 marked」管线有意义，
  // 见文件头说明：marked 会先吃掉反斜杠，所以这里通常不会命中。
  const RE_INLINE_PAREN = /\\\(([\s\S]+?)\\\)/g;
  // 行内：$…$ —— 保守规则：
  //   ① 左边不是 $ 或反斜杠（避免吃掉 $$ 的第二个符号）
  //   ② 内容不以空白开头、也不以空白结尾（KaTeX/markdown-it 的通行做法，
  //      这样「价格 $5 和 $8」不会被误判）
  //   ③ 内容里不能有裸的 $ 或换行
  const RE_INLINE_DOLLAR = /(?:^|[^$\\])\$([^\s$][^$\n]*?[^\s$])\$(?!\$)/g;

  // 占位符：把公式先换成正文里几乎不可能出现的记号，
  // 等 pass2 再统一回填成 KaTeX 的 HTML。
  //
  // ⚠️ 不能用 \u0000 之类的控制字符：HTML 解析器会在 innerHTML 赋值时
  //    把它们**静默丢掉**（实测 `'前\u0000KX0\u0000后'` → `'前KX0后'`），
  //    导致回填阶段找不到占位符，公式全部消失。
  //    这里用 @@...@@ 这种纯 ASCII 组合，并靠「成对出现」来判断。
  const PH_OPEN = "@@KX-MATH-";
  const PH_CLOSE = "-@@";
  let seq = 0;

  function stash(store, html) {
    const key = PH_OPEN + (seq++) + PH_CLOSE;
    store.set(key, html);
    return key;
  }

  function unstash(host, store) {
    if (!store.size) return;
    // 收集所有「可能含占位符」的文本节点
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, null);
    const targets = [];
    while (walker.nextNode()) {
      const t = walker.currentNode;
      if (t.nodeValue && t.nodeValue.indexOf(PH_OPEN) >= 0) targets.push(t);
    }
    targets.forEach((node) => {
      const value = node.nodeValue;
      const frag = document.createDocumentFragment();
      let pos = 0;
      while (true) {
        const start = value.indexOf(PH_OPEN, pos);
        if (start < 0) break;
        const end = value.indexOf(PH_CLOSE, start + PH_OPEN.length);
        if (end < 0) break;
        const key = value.slice(start, end + PH_CLOSE.length);
        const html = store.get(key);
        if (html == null) { pos = start + PH_OPEN.length; continue; }

        if (start > pos) frag.appendChild(document.createTextNode(value.slice(pos, start)));
        const span = document.createElement("span");
        span.className = "rnd-math-slot";
        span.innerHTML = html;
        frag.appendChild(span);
        pos = end + PH_CLOSE.length;
      }
      if (pos === 0) return;                       // 没找到有效占位符，保持原样
      if (pos < value.length) frag.appendChild(document.createTextNode(value.slice(pos)));
      node.parentNode.replaceChild(frag, node);
    });
  }

  // ---- 依赖加载 ----
  let loading = null;
  let cssText = null;         // 内联到底 Shadow DOM 用的样式文本

  /**
   * KaTeX 样式必须**内联进 Shadow DOM**，不能只在文档里挂 <link>。
   *
   * 原因：渲染器的内容在 shadow root 内部，外部的样式表对它不可见 ——
   * 只见「公式 HTML 出来了、却全是没排版的纯文本」这种诡异现象。
   * 另外 CSS 里的 `url(fonts/…)` 是相对 katex.css 的，
   * 放进 shadow root 后会相对**页面**解析，需要改写成
   * 以页面为基准的绝对路径（vendor/katex/fonts/…）。
   */
  const CSS_BASE = "vendor/katex/";   // 页面基准
  function fetchCSS() {
    if (cssText != null) return Promise.resolve(cssText);
    return fetch(CSS_URL)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("HTTP " + r.status))))
      .then((txt) => {
        // 相对字体路径 → 页面基准的绝对路径
        cssText = txt.replace(/url\(fonts\//g, "url(" + CSS_BASE + "fonts/");
        return cssText;
      })
      .catch(() => { cssText = ""; return ""; });
  }

  /** 渲染器在 extraCSS() 里取这段样式，塞进自己的 shadow root */
  function getCSS() { return cssText || ""; }

  function ensure() {
    if (window.katex && cssText != null) return Promise.resolve(true);
    if (loading) return loading;
    loading = Promise.all([
      fetchCSS(),
      window.katex ? Promise.resolve() : new Promise((res) => {
        const s = document.createElement("script");
        s.src = JS_URL;
        s.onload = () => res();
        s.onerror = () => res();
        document.head.appendChild(s);
      }),
    ]).then(() => {
      if (!window.katex) loading = null;
      return !!window.katex;
    });
    return loading;
  }

  /** 把公式源码渲染成 KaTeX HTML；失败时抛错（由调用方降级展示） */
  function render1(tex, displayMode) {
    return window.katex.renderToString(tex, {
      displayMode,
      throwOnError: true,
      strict: "ignore",       // 容忍 amsmath 之外的一些写法，避免整页冒红字
      trust: false,           // 不允许 \htmlClass 之类的注入
      output: "html",         // 纯 HTML + CSS，不依赖 MathML 渲染差异
    });
  }

  /**
   * 预处理 HTML 字符串。
   *
   * ⚠️ 前置条件：window.katex 必须已加载。这里不自己异步加载 ——
   * KaTeX 是纯函数渲染，但 parse() 是同步的，没法 await。
   * 依赖由 MarkdownRenderer.ensureDeps() 负责；若尚未就绪，
   * 这里会**原样返回**（公式代码保持原样，等依赖到位后重建时再处理）。
   */
  function preprocess(html) {
    const store = new Map();
    const stats = { display: 0, inline: 0, failed: 0 };

    // 依赖没到：不做任何替换，返回原文（不计入统计）
    if (!window.katex) return { html, store, stats, skipped: true };

    let out = html;

    // 0) 还原 HTML 实体
    //    marked 会先把源码转义（& → &amp;、< → &lt;），
    //    于是 LaTeX 里的矩阵 / 对齐环境 `&` 变成 `&amp;`、
    //    `\\` 换行变成两段，KaTeX 就认不出来了。
    //    KaTeX 的输入是「源码」而不是 HTML，所以这里要还原回去。
    //    只处理公式内部，避免影响正文里的正常实体。
    const unescapeTex = (s) => String(s)
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'");

    // 1) 行间公式
    out = out.replace(RE_DISPLAY, (m, tex) => {
      try {
        const h = render1(unescapeTex(tex), true);
        stats.display++;
        return stash(store, '<span class="rnd-math rnd-math-display">' + h + "</span>");
      } catch (e) {
        stats.failed++;
        return stash(store, mathError(unescapeTex(tex), e));
      }
    });

    // 2) 行内公式 \(…\)
    out = out.replace(RE_INLINE_PAREN, (m, tex) => {
      try {
        const h = render1(unescapeTex(tex), false);
        stats.inline++;
        return stash(store, '<span class="rnd-math rnd-math-inline">' + h + "</span>");
      } catch (e) {
        stats.failed++;
        return stash(store, mathError(unescapeTex(tex), e));
      }
    });

    // 3) 行内公式 $…$
    out = out.replace(RE_INLINE_DOLLAR, (m, tex) => {
      try {
        const h = render1(unescapeTex(tex), false);
        stats.inline++;
        return stash(store, '<span class="rnd-math rnd-math-inline">' + h + "</span>");
      } catch (e) {
        stats.failed++;
        return stash(store, mathError(unescapeTex(tex), e));
      }
    });

    return { html: out, store, stats };
  }

  /** 渲染失败时的就地提示（保留源码，方便用户改） */
  function mathError(tex, err) {
    const msg = (err && err.message) || "语法错误";
    return '<span class="rnd-math-error" title="' + esc(msg) + '">'
      + esc(tex.trim()) + "</span>";
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  /**
   * 供渲染器在依赖异步就绪后重试。
   * KaTeX 不像 Mermaid 需要「重画 DOM」——它是在 parse 阶段同步产出
   * HTML 的，所以只要依赖到位了重新走一遍渲染流程就行。
   * 这里只提供一个信号：本篇是否还有没处理掉的公式。
   */
  function hasPending(host) {
    if (!host || !host.textContent) return false;
    return /\$\$|\\\(|\$[^\s$][^$\n]*?[^\s$]\$/.test(host.textContent);
  }

  window.MathEnhancer = {
    ensure,
    preprocess,
    unstash,
    hasPending,
    /** 供渲染器把它拼进 extraCSS()：KaTeX 样式必须进 Shadow DOM */
    getCSS,
    /** 依赖是否就绪（渲染器用它决定要不要重渲染）*/
    hasDeps: () => !!window.katex,
  };
})();
