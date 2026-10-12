/**
 * 模块沙箱：能力注入 ctx + 可逆副作用 + 故障边界
 * ============================================
 * 每个模块 = 独立作用域 + 专属 ctx。模块只通过 ctx 访问外部；
 * ctx 上没有的能力 = 访问不到（不是"报错后放行"）。
 * 一切副作用经 ctx.effect 登记，卸载时逆序回滚（热插拔安全）。
 */

export function createSandbox({ moduleId, container, bus, log, permission, security }) {
  const effects = [];
  const ctx = { id: moduleId };

  /** 取能力（白名单 + 权限判定；缺失归一 null） */
  ctx.use = (name) => {
    const impl = container.get(name);
    if (!impl) return null;                          // 缺失归一
    if (!permission.check(`use:${name}`)) return null; // 未授权 → 拒
    return impl;
  };

  /** 对外提供能力（自动登记为可逆副作用；同名冲突时"叠栈"，卸载恢复上一个提供方） */
  ctx.provide = (name, impl) => {
    const prev = container.get(name);            // 记录上一个提供方（可能为 null）
    if (prev) log.record('container.conflict', { moduleId, name });
    container.provide(name, impl);
    ctx.effect(() => {
      if (prev) container.provide(name, prev);   // 恢复上一个提供方
      else container.remove(name);
    });
  };

  /** 登记可逆副作用；返回"单独撤销"函数 */
  ctx.effect = (fn) => {
    effects.push(fn);
    return () => { const i = effects.indexOf(fn); if (i >= 0) effects.splice(i, 1); };
  };

  /** 订阅事件（订阅本身就是副作用，卸载时自动退订） */
  ctx.on = (event, fn) => {
    const off = bus.on(event, fn);
    ctx.effect(off);
    return off;
  };

  ctx.emit = (event, payload) => bus.emit(event, payload);
  ctx.log = (type, data) => log.record(type, { moduleId, ...(data || {}) });

  // 握手辅助（模块可用它产出/校验请求头）
  ctx.handshake = () => security.handshake(moduleId);
  ctx.seal = (payload) => security.seal(moduleId, payload);
  ctx.open = (header, payload) => security.open(header, payload);

  /** 故障边界：包装调用，异常只影响自己 */
  ctx.safe = (fn, label = 'call') => async (...args) => {
    try { return await fn(...args); }
    catch (e) { log.record('sandbox.error', { moduleId, label, error: String(e) }); return null; }
  };

  /** 卸载：逆序回滚所有副作用 */
  ctx.dispose = () => {
    for (let i = effects.length - 1; i >= 0; i--) {
      try { effects[i](); }
      catch (e) { log.record('sandbox.effect.error', { moduleId, error: String(e) }); }
    }
    effects.length = 0;
  };

  return ctx;
}
