/**
 * 渲染器统一入口
 * ==============
 *
 * 负责：
 *   1. 按序注入各渲染器所需的 vendor 依赖（仅首次）
 *   2. 加载渲染器实现并登记到 registry
 *   3. 对外暴露 ensureRenderers() / 以及 registry 的再导出
 *
 * 用法：
 *   import { ensureRenderers, candidatesFor, list } from './core/renderers/index.js';
 *   await ensureRenderers();                 // 加载全部已登记的渲染器
 *   await ensureRenderers(['markdown']);     // 只加载指定的（按需）
 *
 * 新增一个渲染器（例如 Typst）只需两步：
 *   ① 写 core/renderers/typst.js，实现 Renderer 子类
 *   ② 在下面的 RENDERERS 数组里加一行 { id:'typst', dep:'...', src:'...' }
 */

import { register, get, list, candidatesFor, tagFor, has, langsOf } from './registry.js';
import { log } from '../log.js';

// ---- vendor 依赖清单（去重、按序加载）----
// 渲染器实现文件会在其 meta.deps 里声明自己需要哪些；
// 这里集中放置共享依赖的加载顺序，避免每个渲染器各自重复注入。
// 注意：loadScript 用 <script src>，路径相对「页面 URL」（即 index.html 所在目录），
// 因此这里是 './vendor/...' 而非相对本文件。
const VENDOR = [
  './vendor/marked.min.js',
  './vendor/purify.min.js',
  './vendor/highlight.min.js',
  './vendor/lang/aliases.js',
  // 注意：不加载 vendor/lang-loader.js。
  // 原版 lang-loader 会在加载时请求后端 /api/lang-stats（语言使用频率统计），
  // 纯前端产品没有该后端，只会制造 404 噪音。
  // LangLoader 已由 markdown 渲染器内的 ensureShim() 完整实现。
  './vendor/emoji-common.js',
  './vendor/emoji-loader.js',
  './vendor/flag-polyfill.js',
];

// ---- 渲染器实现清单 ----
// 新增渲染器 = 加一行。
// 注意：src 是相对「本文件」的路径（走 import()），故为 './markdown.js'。
const RENDERERS = [
  { id: 'markdown', src: './markdown.js' },
  // { id: 'typst',  src: './typst.js' },   ← 将来加这里
];

// ---- 增强模块（挂在某个渲染器的 postProcess 上，不是独立渲染器）----
// 这些文件不注册自定义元素，只是往 window 上挂一个 Enhancer 对象；
// 由使用它们的渲染器（目前是 markdown.js）在 ensureDeps 里按需加载 vendor 单文件。
//
// 这里仅列出以便文档化：
//   math.js     → window.MathEnhancer      （KaTeX 公式）
//   mermaid.js  → window.MermaidEnhancer   （Mermaid 图表）
//   markmap.js  → window.MarkmapEnhancer   （markmap 思维导图）
//
// 注意：它们必须**早于**渲染器实现加载，因为实现里直接读 window.MathEnhancer。
//
// 顺序要求：markmap 的依赖里会用到 KaTeX（脑图内公式），
// 而它在 ensure() 内部会 await MathEnhancer.ensure()，所以顺序上
// math 在 markmap 之前更符合直觉（此处即如此），但即使反了也能自愈。
const ENHANCERS = [
  './math.js',
  './mermaid.js',
  './markmap.js',
];

let bootPromise = null;

/** 载入单个脚本（普通 script，供全局对象如 marked/hljs 使用）*/
function loadScript(src) {
  return new Promise((res, rej) => {
    if (document.querySelector(`script[data-rnd="${src}"]`)) return res();
    const s = document.createElement('script');
    s.src = src;
    s.dataset.rnd = src;
    s.onload = () => res();
    s.onerror = () => rej(new Error('加载失败: ' + src));
    document.head.appendChild(s);
  });
}

/** 载入渲染器实现模块（ES Module）
 *
 * 注意：这里的 URL **不能**加 ?t= 缓存击穿参数。
 * core/ 下的渲染器是「单例基础设施」，一旦加上时间戳，
 * base.js / registry.js 会被加载成多份独立实例 —— 各自持有不同的
 * registry Map 与 RendererABC，导致「元素注册成功但注册表查不到」这类怪象。
 * 缓存击穿只对需要热重载的 pages/*.js 有意义（由 loader.js 负责）。
 */
function loadModule(src) {
  return import(src);
}

/**
 * 确保渲染器可用。
 * @param {string[]} [only] 只加载指定 id 的渲染器；省略则加载全部
 */
export function ensureRenderers(only) {
  if (bootPromise) return bootPromise;

  const want = Array.isArray(only) && only.length
    ? RENDERERS.filter((r) => only.includes(r.id))
    : RENDERERS;

  bootPromise = (async () => {
    // 1) 先加载基础类（渲染器实现依赖 window.RendererABC）
    await loadModule('./base.js');
    // base.js 不静态依赖 registry.js（避免循环依赖），由这里注入注册表
    if (window.RendererABC && window.RendererABC.useRegistry) {
      window.RendererABC.useRegistry({ register });
    }

    // 2) 加载共享 vendor（去重）
    const needVendor = new Set();
    want.forEach((r) => {
      // 每个渲染器的依赖都来自共享 VENDOR 列表，这里全量保证顺序
      VENDOR.forEach((v) => needVendor.add(v));
    });
    for (const v of needVendor) {
      try { await loadScript(v); }
      catch (e) {
        log.warn({ source: 'cpu', target: 'fe', type: 'warn', payload: `vendor 加载失败（非致命）: ${v} ${e.message}` });
      }
    }

    // 3) 加载增强模块（公式 / 图表）—— 必须早于渲染器实现，
    //    因为实现里直接读 window.MathEnhancer / window.MermaidEnhancer
    for (const e of ENHANCERS) {
      try {
        await loadModule(e);
      } catch (err) {
        log.error({ source: 'cpu', target: 'fe', type: 'error', payload: `增强模块 ${e} 加载失败: ${err && err.message}` });
      }
    }

    // 4) 加载并登记渲染器实现
    for (const r of want) {
      try {
        await loadModule(r.src);
      } catch (e) {
        log.error({ source: 'cpu', target: 'fe', type: 'error', payload: `渲染器 ${r.id} 加载失败: ${e && e.message}` });
      }
    }
    return list();
  })();

  return bootPromise;
}

/**
 * 确保「能渲染某语言」的渲染器已加载。
 * UI 只需给语言名，不必知道是哪个渲染器。
 */
export async function ensureForLang(lang) {
  const tag = tagFor(lang);
  if (tag) { await ensureRenderers(); return tag; }
  // 语言未知：保守起见全量加载
  await ensureRenderers();
  return tagFor(lang);
}

export { register, get, list, candidatesFor, tagFor, has, langsOf };
