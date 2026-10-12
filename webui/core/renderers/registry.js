/**
 * 渲染器注册表
 * ============
 *
 * 职责：登记「哪个渲染器能渲染哪些语言」，供 UI 查询与分发。
 *
 * 调用方式：
 *   import { register, get, list, candidatesFor, tagFor } from './registry.js';
 *   register(SomeRendererClass);                  // 读取其 static meta
 *   candidatesFor('typst')  // => ['typst-renderer', ...]  可渲染该语言的渲染器
 *   tagFor('typst')         // => 'typst-renderer'         默认渲染器标签
 *
 * 设计意图：UI 不需要知道具体渲染器类，只认「标签名」和「语言」，
 * 新增一个渲染器 = 实现子类 + register() 一行，演示页/外壳零改动。
 */

const registry = new Map();   // tagName -> { Ctor, meta }
const langIndex = new Map();  // lang -> [tagName, ...]（按注册顺序，第一个是默认）

/**
 * 注册一个渲染器类。
 * 读取其 static meta = { id, title, langs: ['markdown','md'], ... }
 */
export function register(Ctor) {
  const meta = (Ctor && Ctor.meta) || {};
  const tag = Ctor && Ctor.tagName;
  if (!tag) throw new Error('[Registry] 渲染器缺少 static get tagName()');

  const entry = {
    Ctor,
    tagName: tag,
    id: meta.id || tag,
    title: meta.title || meta.id || tag,
    langs: Array.isArray(meta.langs) ? meta.langs.slice() : [],
    deps: Array.isArray(meta.deps) ? meta.deps.slice() : [],
    meta,
  };
  registry.set(tag, entry);

  // 重建语言索引（同一语言可被多个渲染器声明，注册顺序即优先级）
  langIndex.clear();
  for (const e of registry.values()) {
    for (const lang of e.langs) {
      const key = String(lang).toLowerCase();
      if (!langIndex.has(key)) langIndex.set(key, []);
      if (!langIndex.get(key).includes(tag)) langIndex.get(key).push(tag);
    }
  }
  return entry;
}

export function get(tag) {
  return registry.get(tag);
}

/** 所有已注册渲染器（供 UI 列下拉）*/
export function list() {
  return Array.from(registry.values()).map((e) => ({
    tagName: e.tagName,
    id: e.id,
    title: e.title,
    langs: e.langs.slice(),
  }));
}

/** 能渲染某语言的全部渲染器标签名（首个为默认）*/
export function candidatesFor(lang) {
  return (langIndex.get(String(lang || '').toLowerCase()) || []).slice();
}

/** 某语言的首选渲染器标签名；找不到返回 null */
export function tagFor(lang) {
  const c = candidatesFor(lang);
  return c.length ? c[0] : null;
}

/** 该语言是否有可用渲染器 */
export function has(lang) {
  return candidatesFor(lang).length > 0;
}

/** 反查：某渲染器声明支持的语言 */
export function langsOf(tag) {
  const e = registry.get(tag);
  return e ? e.langs.slice() : [];
}
