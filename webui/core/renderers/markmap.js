/**
 * 思维导图渲染（markmap）
 * ======================
 *
 * 与 math.js / mermaid.js 同样是「增强模块」，挂在 markdown 渲染器的
 * postProcess 钩子上，负责把 ```markmap 代码块变成可折叠的思维导图。
 *
 * 它解决的是「大纲式脑图」这个场景：
 *   把文档的标题层级（# / ## / ###）直接变成一张可交互的树状脑图 ——
 *   和 Mermaid 的 `mindmap` 是**两种范式**：
 *     - Mermaid mindmap = 语义型：手写「分支 → 子分支」表达概念关系，放射状
 *     - markmap        = 结构型：Markdown 大纲可视化，逐级缩进、可折叠
 *   两者互补，不是替代关系。
 *
 * ---------------------------------------------------------------------------
 * 依赖（3 个文件，共约 1MB，比 Mermaid 的 2.5MB 小一半）
 * ---------------------------------------------------------------------------
 *   vendor/markmap/d3.min.js              → window.d3
 *   vendor/markmap/markmap-view.min.js    → window.markmap.{Markmap, globalCSS, ...}
 *   vendor/markmap/markmap-lib.iife.js    → window.markmap.{Transformer, ...}
 *
 * ⚠️ 两个极易踩的坑（都是实测踩出来的）：
 *
 *   1. **markmap-lib 必须用 `dist/browser/index.iife.js`**
 *      包的入口是 `dist/index.js`（Node 版）—— 浏览器加载它**不挂全局、
 *      静默失败**，且文件名在官方文档里毫不显眼。
 *      判据：只有 iife / mjs 版本会往 `window.markmap` 上挂东西。
 *
 *   2. **两个文件是「合并」而非「覆盖」window.markmap**
 *      它们的 IIFE 结尾都是 `(this.markmap = this.markmap || {}, deps)` ——
 *      view 挂 Markmap、lib 挂 Transformer，**必须按顺序加载**，
 *      顺序反了后加载的会把先加载的挤掉（因为 `|| {}` 只在不存在时新建）。
 *      实测顺序：d3 → view → lib。
 *
 * 另外 markmap-lib 的 IIFE 第二参数是 `window.katex`（可选，用于脑图里的公式）。
 * 所以本模块的 ensure() **先等 KaTeX 就绪**再加载 lib，否则脑图里的公式不会渲染。
 *
 * ---------------------------------------------------------------------------
 * 缩放与拖拽限制
 * ---------------------------------------------------------------------------
 * markmap 内部的 d3.zoom **默认无任何约束**（实测 scaleExtent = [0, null]、
 * translateExtent = [[null,null],[null,null]]），可以无限放大、把内容拖到天边。
 * 本模块补上三层限制：
 *
 *   ① scaleExtent      基准 = 初始自适应缩放，区间 [基准×0.5, 基准×3]
 *   ② translateExtent  内容包围盒 + 40px 余量（世界坐标）
 *   ③ 关掉 markmap 自带的滚轮平移（它走 zoom.transform，会绕过上面两条）
 *
 * ⚠️ 关键陷阱：**d3 的程序化 `zoom.transform()` 不套用约束**，
 *    只有真实手势（滚轮/拖拽）才会被 scaleExtent / translateExtent 钳制。
 *    所以验证时**必须用真实鼠标事件**，用 `zoom.transform` 造数据会得到
 *    「限制没生效」的错误结论。
 *
 * ---------------------------------------------------------------------------
 * 主题
 * ---------------------------------------------------------------------------
 * markmap 比 Mermaid 省事得多：它把配色拆成「CSS 变量」，
 * 且**自带 `.markmap-dark` 暗色类**（内置一套暗色变量）。
 * 所以切主题**不需要重新渲染**，只要给容器换 class 即可 ——
 * 这是它相对 Mermaid（颜色固化进 SVG、必须重画）的一个实际优势。
 */
(function () {
  "use strict";

  const D3_URL = "vendor/markmap/d3.min.js";
  const VIEW_URL = "vendor/markmap/markmap-view.min.js";
  const LIB_URL = "vendor/markmap/markmap-lib.iife.js";

  // 脑图画布高度（px）。写成常量，因为 width/height 属性要给 d3-zoom
  // 一个可解析的数字（见 renderOne 里的说明），CSS 那边也复用同一个值。
  const MM_SVG_H = 320;

  // ---- 缩放 / 平移限制 ----
  //
  // markmap 内部的 d3.zoom 默认 **完全没有约束**（实测 scaleExtent = [0, null]、
  // translateExtent = [[null,null],[null,null]]），所以可以无限放大、无限拖走。
  //
  // 这里给出三层限制：
  //   ① scaleExtent      相对「初始自适应缩放」的倍数区间（下限有绝对兜底）
  //   ② translateExtent  按内容包围盒 + 余量约束平移
  //   ③ 关掉 markmap 自带的滚轮平移（见 renderOne 的 options 说明）
  const MIN_ZOOM_FACTOR = 0.5;   // 最小 = 初始适配比例 × 0.5（能再缩小一半）
  const MAX_ZOOM_FACTOR = 3;     // 最大 = 初始适配比例 × 3
  const PAN_PAD = 40;            // 允许拖出内容边界的余量（世界坐标 px）

  /**
   * 缩放上限的**绝对下限**。
   *
   * ⚠️ 为什么必须有它：markmap 的 autoFit 让「基准缩放」随内容增大而变小 ——
   * 节点多的图会 fit 成很小的 scale。实测 216 节点 / 20 层的图
   * base = 0.0693，若上限只写 `base × 3 = 0.208`，
   * 而文字在 world 坐标是 16px → 屏幕上只有 16 × 0.208 ≈ **3.3px**，
   * 也就是**这张图永远看不清**，而且用户没有任何办法放大。
   *
   * 取 1.5 是因为：16px 文字 × 1.5 = 24px，清晰可读；
   * 同时它只是"上限"，不影响初始视图，也不会让小图变得能无限放大。
   */
  const READABLE_ZOOM = 1.5;

  // 壳层样式（拼在 markmap 自带 globalCSS 之后）
  const MM_CSS = [
    ".rnd-mm{background:var(--rnd-panel-2);border:1px solid var(--rnd-border);border-radius:8px;",
    "  margin:.8em 0;padding:10px;overflow:hidden}",
    // 未渲染完成时，源码以等宽小字占位，避免高度跳变太突兀
    ".rnd-mm:not([data-mm-ready]){color:var(--rnd-muted);font-size:.85em;",
    "  font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}",
    ".rnd-mm-svg{display:block;width:100%;height:320px}",
    // markmap 的圆点默认用 currentColor，暗色下要能看清
    ".rnd-mm .markmap-node>circle{stroke-width:2}",
    ".rnd-mm-error{border-color:#ff6b6b;background:rgba(255,107,107,.08)}",
    ".rnd-mm-msg{color:#ff6b6b;font-weight:600;font-size:0.9286rem;margin-bottom:6px}",
    ".rnd-mm-src{margin:0;padding:0;background:none;border:none;color:var(--rnd-muted);",
    "  font-family:ui-monospace,Consolas,monospace;font-size:0.8571rem;line-height:1.5;",
    "  white-space:pre-wrap;word-break:break-word}",
  ].join("");

  // 依赖已就绪时保存的实例（Transformer 构造一次即可复用）
  let transformer = null;
  let loading = null;
  let seq = 0;
  const queue = new Set();          // 待渲染的宿主节点（去重）
  const hostTokens = new Map();     // host -> 当前轮次
  const maps = new WeakMap();       // holder -> Markmap 实例（便于 resize/fit）

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }

  // ---- 依赖加载 ----

  function loadScript(src) {
    return new Promise((res) => {
      if (document.querySelector('script[data-mm-dep="' + src + '"]')) return res(true);
      const s = document.createElement("script");
      s.src = src;
      s.dataset.mmDep = src;
      s.onload = () => res(true);
      s.onerror = () => res(false);
      document.head.appendChild(s);
    });
  }

  /**
   * 按序加载依赖。
   *
   * 顺序不能变（见文件头「坑 2」）：d3 → view → lib。
   * 且 lib 之前要先保证 KaTeX 就绪（lib 的 IIFE 会读取 window.katex）。
   */
  function ensure() {
    if (window.markmap && window.markmap.Markmap && window.markmap.Transformer) {
      return Promise.resolve(true);
    }
    if (loading) return loading;

    loading = (async () => {
      // 1) d3（markmap-view 的 IIFE 第二参数就是它）
      if (!window.d3) {
        const ok = await loadScript(D3_URL);
        if (!ok || !window.d3) { loading = null; return false; }
      }
      // 2) markmap-view → window.markmap.Markmap
      if (!window.markmap || !window.markmap.Markmap) {
        const ok = await loadScript(VIEW_URL);
        if (!ok || !window.markmap || !window.markmap.Markmap) { loading = null; return false; }
      }
      // 3) KaTeX 先就绪，再加载 markmap-lib（lib 会把 window.katex 当参数拿走）
      if (window.MathEnhancer && window.MathEnhancer.ensure) {
        try { await window.MathEnhancer.ensure(); } catch (e) { /* 非致命 */ }
      }
      // 4) markmap-lib → window.markmap.Transformer
      if (!window.markmap.Transformer) {
        const ok = await loadScript(LIB_URL);
        if (!ok || !window.markmap.Transformer) { loading = null; return false; }
      }
      try {
        transformer = new window.markmap.Transformer();
      } catch (e) {
        console.error("[MarkmapEnhancer] Transformer 构造失败:", e);
        loading = null;
        return false;
      }
      return true;
    })();

    return loading;
  }

  /** 供渲染器拼进 extraCSS()：markmap 的样式必须进 Shadow DOM */
  function getCSS() {
    const base = (window.markmap && window.markmap.globalCSS) || "";
    // 壳层微调：容器留白、SVG 自适应宽度、折叠圆点颜色跟随主题
    return base + MM_CSS;
  }

  // ---- 渲染 ----

  /** 渲染宿主里所有待渲染的脑图块（与 mermaid.js 同样的序列号并发控制） */
  async function renderHost(host, token) {
    const holders = Array.from(host.querySelectorAll("[data-mm-id]:not([data-mm-ready])"));
    for (const holder of holders) {
      if (token !== hostTokens.get(host)) return;
      if (!holder.isConnected) continue;
      await renderOne(holder);
    }
    host.dispatchEvent(new CustomEvent("rnd-mm-settled", { bubbles: true }));
  }

  /**
   * 算出 markmap 的「初始适配缩放」（即 autoFit 会得到的 scale）。
   *
   * ⚠️ 这里**直接按 markmap fit() 的公式复算**，而不是去读 transform。
   * 原因：读 transform 有严格的时序要求 —— 实测逐帧采样显示
   *   frame 0: rect 就绪但 transform 还是 identity(k=1)
   *   frame 1: autoFit 才把 scale 写回（间隔仅 ~3ms）
   * 「尺寸就绪」≠「适配完成」，早一帧读就会拿到 1。
   * 而复算不依赖时机，还能在容器尺寸变化后随时重算（fit 会跟着变）。
   *
   * 公式来自 markmap-view 的 fit()：
   *   min(w / naturalW * fitRatio, h / naturalH * fitRatio, maxInitialScale)
   */
  function fitScaleOf(mm, svg) {
    const r = mm.state && mm.state.rect;
    if (!r) return null;
    const naturalW = r.x2 - r.x1;
    const naturalH = r.y2 - r.y1;
    if (!isFinite(naturalW) || !isFinite(naturalH) || naturalW <= 0) return null;
    const box = svg.getBoundingClientRect();
    if (!(box.width > 0)) return null;          // 容器不可见（display:none）时算不出
    const o = mm.options || {};
    const fitRatio = typeof o.fitRatio === "number" ? o.fitRatio : 0.95;
    const maxInitial = typeof o.maxInitialScale === "number" ? o.maxInitialScale : 2;
    const k = Math.min(
      (box.width / naturalW) * fitRatio,
      (box.height / Math.max(naturalH, 1)) * fitRatio,
      maxInitial
    );
    return isFinite(k) && k > 0 ? k : null;
  }

  /**
   * 给一个脑图套上缩放 / 平移限制。
   * 返回 false 表示「布局还没完成 / 容器不可见」，调用方应稍后重试。
   */
  function applyLimits(holder, mm) {
    if (!mm || !mm.zoom) return false;
    const svg = holder.querySelector("svg");
    if (!svg) return false;

    const r = mm.state && mm.state.rect;
    // 布局未完成时 rect 是全 0（实测初始值 {x1:0,y1:0,x2:0,y2:0}）
    if (!r || !isFinite(r.x1) || !isFinite(r.x2) || !(r.x2 > r.x1)) return false;

    const base = fitScaleOf(mm, svg);
    if (base == null) return false;
    // 记到 dataset 上仅供排查（真正的来源是复算，不是这个值）
    holder.dataset.mmBase = String(base);

    // ① 缩放上下限
    //    下限跟着 base 走（允许再缩一半）；
    //    上限取 max(base×3, READABLE_ZOOM) —— 后者是关键兜底：
    //    大图 base 很小（实测 216 节点图 base=0.069），
    //    只给 base×3 会让图永远看不清（详见 READABLE_ZOOM 的注释）。
    const minK = base * MIN_ZOOM_FACTOR;
    const maxK = Math.max(base * MAX_ZOOM_FACTOR, READABLE_ZOOM);
    mm.zoom.scaleExtent([minK, Math.max(maxK, minK)]);

    // ② 平移范围：内容包围盒 + 余量（世界坐标）
    //    d3 的语义是「视口必须留在 translateExtent 之内」，
    //    所以给的是内容范围而不是可视范围。
    mm.zoom.translateExtent([
      [r.x1 - PAN_PAD, r.y1 - PAN_PAD],
      [r.x2 + PAN_PAD, r.y2 + PAN_PAD],
    ]);
    return true;
  }

  /**
   * 等布局就绪后上限制。
   * 注意：这里**不需要**再等两帧（基准是复算出来的，不依赖 transform 时机）。
   */
  function scheduleLimits(holder, mm) {
    let tries = 0;
    const tick = () => {
      if (!holder.isConnected) return;
      if (applyLimits(holder, mm)) { watchResize(holder, mm); return; }
      if (++tries < 120) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /**
   * 容器尺寸变化后重新套限制。
   *
   * 为什么必须做：markmap 自己挂了 ResizeObserver，尺寸一变就 `renderData()`，
   * 而 `renderData()` **末尾会再调一次 `fit()`**（`if (autoFit) this.fit()`），
   * 于是基准缩放跟着变 —— 旧的 scaleExtent 就失效了
   * （可能出现「初始视图落在限制区间之外」，表现为第一次滚轮方向反了）。
   * 这里在尺寸稳定后重算一次。
   */
  const resizeObservers = new WeakMap();
  function watchResize(holder, mm) {
    if (resizeObservers.has(holder)) return;
    if (typeof ResizeObserver !== "function") return;
    let timer = null;
    const ro = new ResizeObserver(() => {
      clearTimeout(timer);
      // 防抖：markmap 自己的 ResizeObserver 也有 100ms 防抖，等它先跑完
      timer = setTimeout(() => {
        if (!holder.isConnected) return;
        // fit 之后 transform 已变，清掉缓存的基准并重算
        applyLimits(holder, mm);
      }, 260);
    });
    ro.observe(holder);
    resizeObservers.set(holder, ro);
  }

  async function renderOne(holder) {
    const code = holder.textContent || "";
    try {
      const { root } = transformer.transform(code);
      if (!holder.isConnected) return false;

      // markmap 需要一个 <svg> 作为画布
      holder.innerHTML = "";
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "rnd-mm-svg");
      // ⚠️ 必须给 width/height 一个**具体数字**，不能只靠 CSS 的 100%。
      // 原因：markmap 内部会 `svg.call(d3.zoom())`，而 d3-zoom 初始化时
      // 走 defaultExtent → 读 `svg.width.baseVal.value`。若 width 是百分比
      // （或没有 width 属性），Chrome 会抛
      //   NotSupportedError: Could not resolve relative length
      // 这个错误是**异步**抛出的（发生在 d3 的过渡/事件回调里），
      // 我们的 try/catch 兜不住，会直接变成页面未捕获异常。
      // 实测：只在「主题切换导致重渲染」时触发（首屏反而正常）。
      // 给了数字属性后 d3 能算出 extent；视觉上仍由 CSS 的 width:100% 控制
      // （CSS 优先级高于 presentation attribute），所以响应式不受影响。
      const box = holder.getBoundingClientRect();
      const vw = Math.max(320, Math.round(box.width) || 800);
      const vh = MM_SVG_H;
      svg.setAttribute("width", String(vw));
      svg.setAttribute("height", String(vh));
      holder.appendChild(svg);

      const mm = window.markmap.Markmap.create(svg, {
        // 不播入场动画：内容区可能不可见，动画会卡在起点
        duration: 0,
        // 自动缩放到容器大小
        autoFit: true,
        // ⚠️ 关掉 markmap 自带的「滚轮平移」。
        //
        // 原因：它的 handlePan 走的是 `zoom.transform()`，而 **d3 的程序化
        // transform 会绕过 scaleExtent / translateExtent**（实测：直接设
        // translate(-99999,-99999) 能原样生效）。也就是说只要它开着，
        // 滚轮就能把内容拖到任意远处，我们的平移限制形同虚设。
        // 关掉后：滚轮 = 缩放（受限），拖拽 = 平移（受限，走 d3-zoom 手势路径）。
        pan: false,
        // 同时把「滚轮=平移」的判定关掉，否则 Mac 上（默认 scrollForPan=true）
        // 普通滚轮会被 d3-zoom 的 filter 拒绝，变成滚轮完全没反应。
        // 显式关掉后各平台行为一致：滚轮一律缩放。
        scrollForPan: false,
        // ⚠️ 刻意**不传 `color`**，用 markmap 内置配色（schemeCategory10）。
        //
        // 踩过的坑：markmap 的 deriveOptions 用 `color.length === 1` 判断
        // 「单色」、`color.length` 判断「调色板数组」——
        // 传一个函数进去时它的 `length` 恰好是**形参个数**，
        // 于是被误判成单色数组，取 `color[0]`（undefined），
        // 结果所有分支都被涂成同一个颜色（实测是 #bab0ab 灰）。
        // 视觉后果很迷惑：连线与文字同色，横向连接线看起来像"下划线"。
        // 内置配色本身就足够好看且明暗通吃，没必要自己造。
      }, root);

      // ③ 套上缩放 / 平移限制（布局是异步的，内部会等 rect 就绪）
      scheduleLimits(holder, mm);

      maps.set(holder, mm);
      // 首屏就可能是暗色主题，渲染完立刻对齐一次
      holder.classList.toggle("markmap-dark", isDark());
      holder.dataset.mmReady = "1";
      delete holder.dataset.mmState;
      holder.classList.remove("rnd-mm-error");
      return true;
    } catch (err) {
      if (!holder.isConnected) return false;
      holder.dataset.mmReady = "1";
      holder.dataset.mmState = "error";
      holder.classList.add("rnd-mm-error");
      holder.innerHTML =
        '<div class="rnd-mm-msg">脑图渲染失败</div>'
        + '<pre class="rnd-mm-src">' + esc(String((err && err.message) || err)) + "\n\n"
        + esc(code.trim()) + "</pre>";
      return false;
    }
  }

  function flush() {
    const hosts = Array.from(queue);
    queue.clear();
    hosts.forEach((host) => {
      if (!host.isConnected) return;
      const token = (hostTokens.get(host) || 0) + 1;
      hostTokens.set(host, token);
      ensure()
        .then((ok) => {
          if (token !== hostTokens.get(host)) return;
          if (!ok) {
            host.querySelectorAll("[data-mm-id]:not([data-mm-ready])").forEach((el) => {
              el.dataset.mmReady = "1";
              el.dataset.mmState = "error";
              el.classList.add("rnd-mm-error");
              el.innerHTML = '<div class="rnd-mm-msg">脑图库加载失败</div>';
            });
            host.dispatchEvent(new CustomEvent("rnd-mm-settled", { bubbles: true }));
            return;
          }
          return renderHost(host, token);
        })
        .catch((e) => console.error("[MarkmapEnhancer]", e));
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // ---- 主题 ----
  // markmap 把配色放在 CSS 变量里并自带 .markmap-dark，
  // 所以切主题**只要换一个 class**，不用重新渲染 ——
  // 这一点明显优于 Mermaid（后者把颜色固化进 SVG，必须整篇重画）。
  function applyTheme(host) {
    if (!host || !host.querySelectorAll) return;
    const dark = isDark();
    host.querySelectorAll("[data-mm-id]").forEach((el) => {
      el.classList.toggle("markmap-dark", dark);
    });
  }

  window.MarkmapEnhancer = {
    ensure,
    /** 找出宿主里所有待渲染的脑图块，排队渲染 */
    schedule(host) {
      if (!host || !host.querySelector) return 0;
      const todo = host.querySelectorAll("[data-mm-id]:not([data-mm-ready])");
      if (!todo.length) return 0;
      queue.add(host);
      Promise.resolve().then(flush);
      return todo.length;
    },
    /**
     * 主题变化：markmap 不需要重渲染（配色走 CSS 变量），
     * 只需切换 .markmap-dark 并重设分支色。
     */
    invalidate(host) {
      applyTheme(host);
    },
    /** 容器尺寸变化后重新自适应（会同时重设限制，因为基准缩放变了） */
    fit(host) {
      if (!host || !host.querySelectorAll) return;
      host.querySelectorAll("[data-mm-id]").forEach((el) => {
        const mm = maps.get(el);
        if (mm && mm.fit) {
          try {
            mm.fit();
            // fit 是程序化 transform，会绕过限制；容器尺寸变化后适配比例也变了
            // —— 重新套一次限制（基准是复算的，所以能立刻拿到新值）。
            applyLimits(el, mm);
          } catch (e) {}
        }
      });
    },
    /** 对外暴露：给某个宿主里的脑图重新套上缩放/平移限制 */
    applyLimits(host) {
      if (!host || !host.querySelectorAll) return;
      host.querySelectorAll("[data-mm-id]").forEach((el) => {
        const mm = maps.get(el);
        if (mm) applyLimits(el, mm);
      });
    },
    /** 统计：已渲染 / 失败 / 总计（给状态栏用）*/
    stats(host) {
      if (!host || !host.querySelectorAll) return { total: 0, done: 0, failed: 0 };
      const all = host.querySelectorAll("[data-mm-id]");
      let done = 0, failed = 0;
      all.forEach((el) => {
        if (el.dataset.mmReady) {
          done++;
          if (el.dataset.mmState === "error") failed++;
        }
      });
      return { total: all.length, done, failed };
    },
    getCSS,
    hasDeps: () => !!(window.markmap && window.markmap.Markmap && window.markmap.Transformer),
  };
})();
