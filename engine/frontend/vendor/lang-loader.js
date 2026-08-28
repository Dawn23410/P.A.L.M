/* lang-loader.js —— highlight.js 语法高亮按需加载与自适应缓存
 * 设计（与 app.js 配合实现「流式感知的延迟渲染」）：
 *  1. 初始包仅含 common 核心 + 终端语法(powershell/dos)；其余 192 种语言按需异步加载。
 *  2. 本地优先：/vendor/lang/<name>.min.js；本地缺失再回退公网 CDN。
 *  3. 三级缓存：
 *     - 会话内 Set：本次使用常驻；3h 空闲自动释放（下次使用重新加载）。
 *     - 服务端 JSON 长时间计数：每次加载累计计数（持久化到 lang_stats.json，跨会话长期保留）。
 *       计数 ≥ 阈值(默认10) 的语言包，下次启动随初始包一同预载。
 *     - 低频语言：累计不足则不进入预载集，仅按需加载（自然降级）。
 *  4. 对外回调：setReadyHandler(fn(name, ok)) —— 某语言就绪(ok=true)或失败(ok=false)时通知。
 */
(function (global) {
  "use strict";

  var THRESHOLD = 10;                       // 累计计数达到该值则预载
  var IDLE_MS = 3 * 60 * 60 * 1000;         // 会话空闲 3h 释放已加载的语言包
  var CDN = "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/languages/";
  var STATS_URL = "/api/lang-stats";

  var loading = Object.create(null);        // name -> Promise（去重并发加载）
  var sessionLoaded = Object.create(null);  // name -> true（本会话已加载）
  var readyHandler = null;
  var idleTimer = null;

  // 长时间计数缓存
  var statsCache = Object.create(null);     // name -> 累计总次数（服务端 JSON 的本地镜像）
  var pending = Object.create(null);        // name -> 本次会话待提交增量
  var statsReady = false;
  var saveTimer = null;

  function isRegistered(name) {
    return !!(global.hljs && global.hljs.getLanguage && global.hljs.getLanguage(name));
  }

  // 原始围栏名 -> hljs 规范语言名（别名表解析）
  function resolve(raw) {
    if (!raw) return null;
    var n = String(raw).toLowerCase();
    if (global.HLJS_ALIASES && global.HLJS_ALIASES[n]) n = global.HLJS_ALIASES[n];
    return n;
  }

  // ---- 长时间计数（服务端 JSON 文件，跨会话持久）----
  function loadStats() {
    return fetch(STATS_URL, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (obj) {
        statsCache = (obj && typeof obj === "object") ? obj : {};
        statsReady = true;
        return statsCache;
      })
      .catch(function () { statsReady = true; statsCache = {}; return statsCache; });
  }

  function flushPending() {
    saveTimer = null;
    var inc = pending;
    pending = Object.create(null);
    if (Object.keys(inc).length === 0) return;
    try {
      fetch(STATS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ increments: inc })
      }).catch(function () {
        // 提交失败：增量回退，下次重试
        for (var k in inc) pending[k] = (pending[k] || 0) + inc[k];
      });
    } catch (e) {
      for (var k in inc) pending[k] = (pending[k] || 0) + inc[k];
    }
  }

  function scheduleSave() {
    if (saveTimer) return;                    // 防抖：合并短时间内的多次累加
    saveTimer = setTimeout(flushPending, 1000);
  }

  function bumpStat(name) {
    sessionLoaded[name] = true;
    resetIdle();
    statsCache[name] = (statsCache[name] || 0) + 1;
    pending[name] = (pending[name] || 0) + 1;
    scheduleSave();
  }

  function preloadSet() {
    var set = [];
    for (var name in statsCache) {
      if ((statsCache[name] || 0) >= THRESHOLD) set.push(name);
    }
    return set;
  }

  function resetIdle() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      // 长时间未使用：释放会话内已加载的语言包（预载集由服务端 JSON 重新计算，不受影响）
      for (var k in sessionLoaded) delete sessionLoaded[k];
    }, IDLE_MS);
  }

  function loadScript(name) {
    if (loading[name]) return loading[name];
    var p = new Promise(function (resolve) {
      var s = document.createElement("script");
      s.src = "/vendor/lang/" + name + ".min.js";
      s.onload = function () { resolve(true); };
      s.onerror = function () {
        // 本地缺失 -> 公网回退
        var f = document.createElement("script");
        f.src = CDN + name + ".min.js";
        f.onload = function () { resolve(true); };
        f.onerror = function () { resolve(false); };
        document.head.appendChild(f);
      };
      document.head.appendChild(s);
    }).then(function (ok) {
      if (ok && isRegistered(name)) fireReady(name, true);
      else fireReady(name, false);
      return ok;
    });
    loading[name] = p;
    p.then(function () { delete loading[name]; });
    return p;
  }

  // 确保某语言已注册；opts.count=false 时（如预载）不计入使用统计
  function ensure(name, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      if (isRegistered(name)) {
        if (opts.count !== false) bumpStat(name);
        resolve(true);
        return;
      }
      loadScript(name).then(function (ok) {
        if (ok && isRegistered(name)) {
          // 防止并发 ensure 重复计数：仅首次加载计入
          if (opts.count !== false && !sessionLoaded[name]) bumpStat(name);
          resolve(true);
        } else {
          resolve(false);
        }
      });
    });
  }

  function fireReady(name, ok) {
    if (readyHandler) {
      try { readyHandler(name, ok); } catch (e) {}
    }
  }

  // 启动预载：累计使用 ≥ 阈值的语言包，随初始包之后立即加载（不计入统计）
  function preload() {
    preloadSet().forEach(function (name) { ensure(name, { count: false }); });
  }

  // 初始化：先拉取服务端长时间计数，再基于阈值预载
  function init() {
    return loadStats().then(function () { preload(); });
  }

  function setReadyHandler(fn) { readyHandler = fn; }

  global.LangLoader = {
    resolve: resolve,
    isRegistered: isRegistered,
    ensure: ensure,
    preload: preload,
    init: init,
    setReadyHandler: setReadyHandler,
    get THRESHOLD() { return THRESHOLD; }
  };
})(window);
