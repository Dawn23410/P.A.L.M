/**
 * 图表渲染（Mermaid）
 * ===================
 *
 * 与 math.js 同样是「增强模块」，挂在 markdown 渲染器的 postProcess 上。
 *
 * 关键难点（与公式不同）：
 *   Mermaid 是**异步**的，而且会把图渲染进 DOM。
 *   而基类的模板方法用 `innerHTML` 重建内容，会丢掉异步渲染的结果 ——
 *   所以必须自己记住「本篇有哪些图、渲染到什么状态」，重新渲染完再灌回去。
 *
 * 做法：
 *   1. postProcess 时把 ```` ```mermaid ```` 代码块就地换成一个带
 *      `data-mmd-id` 的容器（保留源码在 textContent 里）
 *   2. 异步调用 mermaid 渲染，成功后写入容器
 *   3. 容器被重建（主题切换 / 依赖就绪重渲染）时，靠 `data-mmd-ready`
 *      判断是否已渲染 —— 未就绪就重新排队
 *
 * 主题：Mermaid 的配色靠 initialize() 的全局 themeVariables，
 *   渲染出的 SVG 会把颜色**固化成内联样式**，之后无法靠 CSS 变量换色。
 *   因此主题变化时必须整篇重渲染（由 index.js 的 rnd-theme-change 事件驱动）。
 */

(function () {
  "use strict";

  const JS_URL = "vendor/mermaid.min.js";

  let loading = null;
  let initialized = null;   // 记住上次用的主题，变了要重新 initialize
  let seq = 0;
  const queue = new Set();  // 待渲染的宿主节点（去重）

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }

  /** 把当前主题的配色注入 mermaid */
  function applyTheme() {
    const dark = isDark();
    if (initialized === (dark ? "dark" : "light")) return;
    initialized = dark ? "dark" : "light";

    if (dark) {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: "base",
        securityLevel: "strict",
        fontFamily: "-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
        themeVariables: {
          darkMode: true,
          background: "#1b1f2a",
          primaryColor: "#222736",
          primaryTextColor: "#e6e9ef",
          primaryBorderColor: "#475069",
          secondaryColor: "#2a3040",
          tertiaryColor: "#1b1f2a",
          lineColor: "#8b93a7",
          textColor: "#e6e9ef",
          mainBkg: "#222736",
          nodeBorder: "#475069",
          clusterBkg: "#1f2431",
          clusterBorder: "#3a4257",
          titleColor: "#e6e9ef",
          edgeLabelBackground: "#1b1f2a",
          actorBkg: "#222736",
          actorBorder: "#475069",
          actorTextColor: "#e6e9ef",
          signalColor: "#c3cad6",
          signalTextColor: "#e6e9ef",
          noteBkgColor: "#2f3a2f",
          noteTextColor: "#e6e9ef",
          noteBorderColor: "#4a6b4a",
        },
      });
    } else {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: "base",
        securityLevel: "strict",
        fontFamily: "-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
        themeVariables: {
          darkMode: false,
          background: "#ffffff",
          primaryColor: "#eef2f8",
          primaryTextColor: "#1f2328",
          primaryBorderColor: "#c8d1dd",
          secondaryColor: "#f6f8fa",
          tertiaryColor: "#ffffff",
          lineColor: "#6a737d",
          textColor: "#1f2328",
          mainBkg: "#eef2f8",
          nodeBorder: "#c8d1dd",
          clusterBkg: "#f6f8fa",
          clusterBorder: "#d0d7de",
          titleColor: "#1f2328",
          edgeLabelBackground: "#ffffff",
          actorBkg: "#eef2f8",
          actorBorder: "#c8d1dd",
          actorTextColor: "#1f2328",
          signalColor: "#4a5468",
          signalTextColor: "#1f2328",
          noteBkgColor: "#fdf6d8",
          noteTextColor: "#1f2328",
          noteBorderColor: "#ddd08a",
        },
      });
    }
  }

  function ensure() {
    if (window.mermaid) { applyTheme(); return Promise.resolve(true); }
    if (loading) return loading;
    loading = new Promise((res) => {
      const s = document.createElement("script");
      s.src = JS_URL;
      s.onload = () => {
        if (window.mermaid) { applyTheme(); res(true); }
        else { loading = null; res(false); }
      };
      s.onerror = () => { loading = null; res(false); };
      document.head.appendChild(s);
    });
    return loading;
  }

  /**
   * 统一的「确保依赖 + 配色已就绪」入口。
   *
   * 注意：任何会调用 mermaid API 的地方都必须先 await 它 ——
   * 包括 schedule()/invalidate()。因为渲染器在依赖就绪后会重渲染，
   * 那时 mermaid 可能还没加载完（它是 2.5MB，通常是最后到的），
   * 若直接调 initialize 会抛 "Cannot read properties of undefined"。
   */
  async function ready() {
    await ensure();
    if (window.mermaid) applyTheme();
    return !!window.mermaid;
  }

  /** mermaid 解析失败时，把 message 里的行号 / 期望值也带出来 */
  function readError(err) {
    if (!err) return "渲染失败";
    const raw = err.str || err.message || String(err);
    const line = (err.hash && err.hash.loc && err.hash.loc.first_line);
    return (line != null ? "第 " + line + " 行：" : "") + raw;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  /**
   * 渲染宿主里**所有**待渲染的图表块。
   *
   * 两个易错点：
   *   1. 必须 querySelectorAll —— 一个宿主里可能有好几张图，
   *      只取第一张会让其余的永远停在占位态。
   *   2. 并发控制用「序列号」而不是布尔锁：
   *      每次 flush 使 seq 自增，异步回调只在序号仍然匹配时才执行，
   *      这样重入、重建、主题切换都不会互相顶掉。
   */
  async function renderHost(host, token) {
    const holders = Array.from(host.querySelectorAll("[data-mmd-id]:not([data-mmd-ready])"));
    for (const holder of holders) {
      if (token !== hostTokens.get(host)) return;   // 已被更新的一轮取代
      if (!holder.isConnected) continue;
      await renderOne(host, holder);
    }
    host.dispatchEvent(new CustomEvent("rnd-mmd-settled", { bubbles: true }));
  }

  async function renderOne(host, holder) {
    const id = holder.dataset.mmdId;
    const code = holder.textContent || "";
    try {
      const { svg } = await window.mermaid.render("mmd-" + id + "-" + (seq++), code);
      if (!holder.isConnected) return false;
      holder.innerHTML = svg;
      holder.dataset.mmdReady = "1";
      delete holder.dataset.mmdState;
      holder.classList.remove("rnd-mmd-error");
      return true;
    } catch (err) {
      if (!holder.isConnected) return false;
      holder.dataset.mmdReady = "1";
      holder.dataset.mmdState = "error";
      holder.classList.add("rnd-mmd-error");
      holder.innerHTML =
        '<div class="rnd-mmd-msg">图表渲染失败</div>'
        + '<pre class="rnd-mmd-src">' + esc(readError(err)) + "\n\n" + esc(code.trim()) + "</pre>";
      return false;
    }
  }

  const hostTokens = new Map();   // host -> 当前轮次
  function flush() {
    const hosts = Array.from(queue);
    queue.clear();
    hosts.forEach((host) => {
      if (!host.isConnected) return;
      const token = (hostTokens.get(host) || 0) + 1;
      hostTokens.set(host, token);
      ready()
        .then((ok) => {
          if (token !== hostTokens.get(host)) return;   // 过期轮次，丢弃
          if (!ok) {
            // 依赖加载失败：把所有待渲染容器标记成错误，别卡在占位态
            host.querySelectorAll("[data-mmd-id]:not([data-mmd-ready])").forEach((el) => {
              el.dataset.mmdReady = "1";
              el.dataset.mmdState = "error";
              el.classList.add("rnd-mmd-error");
              el.innerHTML = '<div class="rnd-mmd-msg">图表库加载失败</div>';
            });
            host.dispatchEvent(new CustomEvent("rnd-mmd-settled", { bubbles: true }));
            return;
          }
          return renderHost(host, token);
        })
        .catch((e) => console.error("[MermaidEnhancer]", e));
    });
  }

  window.MermaidEnhancer = {
    ensure,
    ready,
    /** 找出宿主里所有待渲染的图表块，排队渲染 */
    schedule(host) {
      if (!host || !host.querySelector) return 0;
      const todo = host.querySelectorAll("[data-mmd-id]:not([data-mmd-ready])");
      if (!todo.length) return 0;
      queue.add(host);
      // 合帧：一次 postProcess 里可能同时出现好几张图
      Promise.resolve().then(flush);
      return todo.length;
    },
    /** 主题变化：把已渲染的图标记为待重渲染，再排队 */
    invalidate(host) {
      if (!host || !host.querySelectorAll) return;
      host.querySelectorAll("[data-mmd-ready]").forEach((el) => {
        delete el.dataset.mmdReady;
      });
      window.MermaidEnhancer.schedule(host);
    },
    /** 统计：已渲染 / 失败 / 总计（给状态栏用）*/
    stats(host) {
      if (!host || !host.querySelectorAll) return { total: 0, done: 0, failed: 0 };
      const all = host.querySelectorAll("[data-mmd-id]");
      let done = 0, failed = 0;
      all.forEach((el) => {
        if (el.dataset.mmdReady) {
          done++;
          if (el.dataset.mmdState === "error") failed++;
        }
      });
      return { total: all.length, done, failed };
    },
    hasDeps: () => !!window.mermaid,
  };
})();
