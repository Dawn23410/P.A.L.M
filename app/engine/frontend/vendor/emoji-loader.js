/* emoji-loader.js — Emoji 二级加载器 + 使用统计
 * 一级(emoji-common.js)随 UI 同步加载到 window.EMOJI_MAP(常见 300+)。
 * 解析 Markdown 时若遇到不在 EMOJI_MAP 中的短码，调用 note(name) 触发二级加载：
 *   异步注入 /vendor/emoji-full.js，加载完成后把全体短码合并进 EMOJI_MAP，
 *   并触发 readyHandler（仅一次），由 app.js 重建含未注册 emoji 的气泡。
 * 全程不阻塞流式输出：未就绪时短码以原文本 ":name:" 显示，就绪后自然被解析。
 *
 * 使用统计（供服务端按 7 天周期计算命中率、自动扩 common 集合）：
 *   - track(name) 记录每次 emoji 使用（命中 common 或触发 uncommon 都计），
 *     内存计数 + 防抖(1s) POST 到 /api/emoji-stats。
 *   - getStats() 返回本次会话命中率（common 命中 / 总使用）。
 */
window.EmojiLoader = (function () {
  "use strict";

  var FULL_URL = "/vendor/emoji-full.js";
  var STATS_URL = "/api/emoji-stats";
  var SAVE_DEBOUNCE_MS = 1000;

  var loaded = false;     // 二级数据是否已合并
  var loading = null;     // 进行中的加载 Promise（并发去重）
  var readyHandler = null;
  var seenThisRender = new Set(); // 本次 renderMarkdown 遇到的未注册短码

  // 使用计数（本次会话，内存镜像，用于会话级命中率）
  var sessionUse = Object.create(null);
  // 待提交增量（防抖上报）
  var pending = Object.create(null);
  var saveTimer = null;

  function isCommon(name) {
    return !!(window.EMOJI_MAP &&
              Object.prototype.hasOwnProperty.call(window.EMOJI_MAP, name));
  }

  // 渲染开始时清空“本次渲染”计数器
  function beginRender() {
    seenThisRender = new Set();
  }

  // 渲染结束：返回本次遇到的未注册短码集合（并重置）
  function endRender() {
    var s = seenThisRender;
    seenThisRender = new Set();
    return s;
  }

  // 记录一次 emoji 使用（命中率与升舱统计）。isCommon 仅用于本地日志/语义。
  function track(name) {
    if (!name) return;
    sessionUse[name] = (sessionUse[name] || 0) + 1;
    pending[name] = (pending[name] || 0) + 1;
    scheduleSave();
  }

  // 遇到未注册短码：记录并在需要时触发二级加载
  function note(name) {
    // 已加载完成且确认该短码在所有数据中都不存在：跳过重触发，避免死循环
    if (loaded && window.EMOJI_FULL &&
        !Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, name)) {
      return;
    }
    seenThisRender.add(name);
    ensureFull();
  }

  function scheduleSave() {
    if (saveTimer) return;
    saveTimer = setTimeout(flush, SAVE_DEBOUNCE_MS);
  }

  function flush() {
    saveTimer = null;
    var inc = pending;
    pending = Object.create(null);
    if (!Object.keys(inc).length) return;
    try {
      fetch(STATS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ increments: inc }),
        keepalive: true,
      }).catch(function () {
        // 提交失败：增量回退，下次重试
        for (var k in inc) pending[k] = (pending[k] || 0) + inc[k];
      });
    } catch (e) {
      for (var k in inc) pending[k] = (pending[k] || 0) + inc[k];
    }
  }

  // 异步加载并合并全体 emoji；幂等（loaded/loading 去重）
  function ensureFull() {
    if (loaded) return Promise.resolve(true);
    if (loading) return loading;
    loading = new Promise(function (resolve) {
      var sc = document.createElement("script");
      sc.src = FULL_URL;
      sc.onload = function () {
        if (window.EMOJI_FULL && window.EMOJI_MAP) {
          for (var k in window.EMOJI_FULL) {
            if (Object.prototype.hasOwnProperty.call(window.EMOJI_FULL, k)) {
              window.EMOJI_MAP[k] = window.EMOJI_FULL[k];
            }
          }
          loaded = true;
          loading = null;
          resolve(true);
          if (readyHandler) readyHandler();
        } else {
          loading = null;
          resolve(false);
        }
      };
      sc.onerror = function () {
        loading = null;
        resolve(false); // 加载失败：短码保留原文本，不阻塞
      };
      document.head.appendChild(sc);
    });
    return loading;
  }

  // 会话级命中率：common 命中 / 总使用（distinct = 去重后的不同 emoji 数）
  function getStats() {
    var total = 0, distinct = 0, commonDistinct = 0, commonOcc = 0;
    for (var k in sessionUse) {
      if (!Object.prototype.hasOwnProperty.call(sessionUse, k)) continue;
      distinct++;
      total += sessionUse[k];
      if (isCommon(k)) { commonDistinct++; commonOcc += sessionUse[k]; }
    }
    return {
      total: total,
      distinct: distinct,
      commonDistinct: commonDistinct,
      uncommonDistinct: distinct - commonDistinct,
      commonHits: commonOcc,
      uncommonHits: total - commonOcc,
      hitRate: distinct ? commonDistinct / distinct : 1,
      fullLoaded: loaded,
    };
  }

  function setReadyHandler(fn) { readyHandler = fn; }
  function isLoaded() { return loaded; }

  return {
    note: note,
    track: track,
    beginRender: beginRender,
    endRender: endRender,
    ensureFull: ensureFull,
    setReadyHandler: setReadyHandler,
    isLoaded: isLoaded,
    getStats: getStats,
  };
})();
