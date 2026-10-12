/**
 * 页面运行时（内核驱动版）
 * ========================
 * 外壳（index.html）只认「页面 id」与「生命周期」；
 * 真正的加载 / 卸载 / 依赖 / 回滚全部交给底层框架 kernel。
 *
 * 本文件只做薄适配：
 *   - 注册页面 → 在内核登记一个同名插件（define 一次，幂等）
 *   - mount   → kernel.use（装配即挂载 DOM）+ 发 page:show 事件
 *   - hide    → 发 page:hide 事件（保留实例，切换更快）
 *   - unmount → kernel.unuse（逆序回滚副作用：退订 + 销毁 + 移除 DOM）
 *
 * 解耦保证：任一页面抛错只影响自己的容器，外壳与其他页面继续正常工作。
 */
import { bootKernel, getKernel } from './app-kernel.js';
import { pageSetup, pageInstances } from './page-plugin.js';

const registry = new Map();    // id -> { id, title, src }
const defined = new Set();     // 已在内核登记过的页面 id

/** 注册一个页面（幂等：实际 define 在首次 mount 时确保一次） */
export function registerPage(id, { title = id, src }) {
  registry.set(id, { id, title, src });
}

/** 确保内核里已定义该页面插件（只定义一次） */
function ensureDefined(k, id) {
  if (defined.has(id)) return;
  const entry = registry.get(id);
  if (!entry) return;
  k.define('page:' + id, {
    setup: (ctx) => pageSetup(ctx, id, entry.src),
  });
  defined.add(id);
}

export function list() {
  return Array.from(registry.values()).map((m) => ({ id: m.id, title: m.title }));
}

export function get(id) {
  return registry.get(id);
}

export function isLoaded(id) {
  const k = getKernel();
  return !!(k && k.loadedIds.includes('page:' + id));
}

/** 加载并挂载页面到容器；已挂载则只发 show 事件复用。 */
export async function mount(id, container) {
  const k = await bootKernel();
  ensureDefined(k, id);

  if (k.loadedIds.includes('page:' + id)) {
    k.bus.emit('page:show:' + id);
    return pageInstances.get(id) || {};
  }

  await k.use('page:' + id);
  k.bus.emit('page:show:' + id);
  return pageInstances.get(id) || {};
}

/** 隐藏（不销毁），保留内部状态 */
export function hide(id) {
  const k = getKernel();
  if (k) k.bus.emit('page:hide:' + id);
}

/** 彻底卸载页面，释放资源（逆序回滚副作用） */
export async function unmount(id) {
  const k = getKernel();
  if (!k) return;
  await k.unuse('page:' + id);
  pageInstances.delete(id);
}

/**
 * 热重载：销毁旧实例，绕过模块缓存重新装配。
 * 用于开发期改完页面文件后即时生效。
 */
export async function reload(id, container) {
  await unmount(id);
  return mount(id, container);
}
