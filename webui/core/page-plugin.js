/**
 * 页面 → 内核插件 适配器
 * ========================
 * 把页面的「mount(host) -> { onShow, onHide, destroy }」契约接进底层框架：
 *   - 页面默认导出函数仍只在自己的 DOM 子树里跑，外壳只认 host；
 *   - 生命周期副作用登记到 ctx，卸载即逆序回滚（热插拔安全）；
 *   - show / hide 走内核事件总线（订阅本身也是可逆副作用）。
 *
 * 页面不向服务容器暴露能力，只靠 DOM + 事件对外工作，
 * 因此它不需要任何 inject / provides —— 纯粹借内核拿到生命周期与底座。
 */
import { createSandbox as createHost, renderError } from './sandbox.js';

/** 已挂载页面实例：loader 与卸载回滚共享 */
export const pageInstances = new Map();

/** HMR 代次：每次重新挂载都让 import URL 变化，绕过浏览器模块缓存 */
const generation = new Map();
function bust(id) {
  const g = (generation.get(id) || 0) + 1;
  generation.set(id, g);
  return g;
}

/**
 * @param {object} ctx  内核为该插件生成的专属 ctx
 * @param {string} id   页面 id
 * @param {string} src  页面模块路径（相对 webui 根，如 '../pages/chat.js'）
 */
export function pageSetup(ctx, id, src) {
  const stage = document.getElementById('stage');
  const host = createHost(id);
  if (stage) stage.appendChild(host);

  let instance = {};
  const loadPage = async () => {
    const mod = await import(/* @vite-ignore */ `${src}?t=${bust(id)}`);
    const factory = mod.default || mod.mount;
    if (typeof factory !== 'function') {
      throw new Error(`页面 ${id} 未导出 default / mount`);
    }
    instance = (await factory(host)) || {};
    pageInstances.set(id, instance);
  };

  return (async () => {
    try {
      await loadPage();
    } catch (err) {
      // 装配失败：错误界面兜住，不拖垮外壳与其他页面
      renderError(host, id, err);
      instance = {};
      pageInstances.set(id, instance);
    }

    // show / hide：由内核事件总线驱动（卸载时自动退订）
    ctx.on('page:show:' + id, () => {
      host.classList.add('mod-active');
      if (typeof instance.onShow === 'function') instance.onShow();
    });
    ctx.on('page:hide:' + id, () => {
      host.classList.remove('mod-active');
      if (typeof instance.onHide === 'function') instance.onHide();
    });

    // 卸载副作用：逆序回滚 —— 先退订（由 ctx.on 登记），再销毁 + 移除 DOM
    ctx.effect(() => {
      if (typeof instance.destroy === 'function') {
        try { instance.destroy(); } catch (_) { /* 忽略 */ }
      }
      pageInstances.delete(id);
      host.remove();
    });

    return {};   // 页面不向容器暴露能力
  })();
}
