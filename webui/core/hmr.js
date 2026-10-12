/**
 * 热重载（HMR）客户端
 *
 * 开发期：轮询 /__hmr 接口（由内置 devserver.js 提供，带各模块 mtime）
 *         发现 mtime 变化就 reload 对应模块，并重新执行它的 activate
 * 生产期：未提供 devserver 时静默降级，不发请求、不报错
 */

export function startHMR({ endpoint = '/__hmr', interval = 1200, onReload }) {
  const stamp = new Map();
  let alive = true;
  let timer = null;

  async function poll() {
    if (!alive) return;
    try {
      const res = await fetch(endpoint + '?_=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) throw new Error('hmr endpoint unavailable');

      // 光看 res.ok 不够：被别的 HTTP 服务"兜底"时也可能返回 200。
      // 本项目的 devserver 一定返回 { modules: {...}, ts }，
      // 校验这个契约能识别出"页面被不相干的服务器托管"的情况，
      // 从而给出一次明确的错误，而不是刷一屏 404。
      const data = await res.json().catch(() => null);
      if (!data || typeof data !== 'object' || typeof data.modules !== 'object' || !data.modules) {
        throw new Error('not our devserver');
      }

      for (const [id, mtime] of Object.entries(data.modules)) {
        const prev = stamp.get(id);
        stamp.set(id, mtime);
        // 首次记录基线，不触发重载
        if (prev !== undefined && prev !== mtime) {
          console.info(`[HMR] 检测到 ${id} 变更，热重载中…`);
          if (typeof onReload === 'function') onReload(id);
        }
      }
    } catch (err) {
      // 环境不适合热重载（未启 devserver / 被其它服务器托管 / 直接双击打开 HTML）：
      // 停止轮询，只提示一次，避免刷控制台。
      alive = false;
      clearTimeout(timer);
      const where = location.origin;
      console.warn(
        `[HMR] 已停用：${where} 不是本项目的开发服务器（${endpoint} 未按约定响应）。\n` +
        '  热重载与模块按需加载需要它。请用项目自带的服务器启动：\n' +
        '    node core/devserver.js 5173   →   http://localhost:5173'
      );
      return;
    }
    timer = setTimeout(poll, interval);
  }

  poll();

  return () => {
    alive = false;
    clearTimeout(timer);
  };
}
