/**
 * L1 内核（微内核）
 * ================
 * 只做四件事：加载 / 卸载 / 依赖解析 / 生命周期。
 * 外加：服务容器（缺失归一 null）· 事件总线 · 单一装配点。
 * 内核不认识任何具体能力。
 */

import { log } from './log.js';
import { createPermission } from './permission.js';
import { createSecurity } from './security.js';
import { createSandbox } from './sandbox.js';

export async function createKernel() {
  const permission = createPermission({ log });
  const security = await createSecurity({ log });

  const defs = new Map();      // id -> { id, inject[], provides[], setup }
  const loaded = new Map();    // id -> { def, ctx, instance }
  const inflight = new Map();  // id -> Promise（并发 use 去重）
  const services = new Map();  // name -> impl

  // ---- 事件总线 ----
  const listeners = new Map(); // name -> Set<fn>
  const bus = {
    on(name, fn) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(fn);
      return () => listeners.get(name).delete(fn);
    },
    emit(name, payload) {
      (listeners.get(name) || []).forEach((fn) => {
        try { fn(payload); } catch (e) { log.record('bus.error', { name, error: String(e) }); }
      });
    },
  };

  // ---- 服务容器（缺失归一 null）----
  const container = {
    provide(name, impl) { services.set(name, impl); },
    remove(name) { services.delete(name); },
    get(name) { return services.get(name) ?? null; },
    names() { return [...services.keys()]; },
  };

  // ---- 单一装配点：注册（唯一出现"注册"的地方）----
  function define(id, def) {
    defs.set(id, { id, inject: [], provides: [], setup: () => ({}), ...def });
    log.record('kernel.define', { id });
  }

  // ---- 加载（拓扑序带依赖；并发去重；循环检测）----
  async function use(id, stack = []) {
    if (loaded.has(id)) return loaded.get(id).instance;
    const def = defs.get(id);
    if (!def) { log.record('kernel.missing', { id }); return null; }            // 缺失归一
    if (stack.includes(id)) { log.record('kernel.cycle', { id, stack }); return null; } // 循环：先判
    if (inflight.has(id)) return inflight.get(id);                              // 并发去重

    const task = (async () => {
      for (const dep of def.inject) await use(dep, [...stack, id]);             // 先装依赖

      await security.handshake(id);                                             // 握手（读 MK + 随机盐）
      const ctx = createSandbox({ moduleId: id, container, bus, log, permission, security });

      let instance = null;
      try { instance = await def.setup(ctx); }
      catch (e) { log.record('kernel.setup.error', { id, error: String(e) }); }

      const provided = [];
      for (const name of def.provides) {
        const prev = container.get(name);                 // 记录上一个提供方（同名冲突可恢复）
        if (prev) log.record('container.conflict', { id, name });
        const impl = (instance && instance[name]) ?? instance;
        container.provide(name, impl);
        provided.push({ name, prev, impl });              // 记 impl：unuse 时校验自己是否仍是当前提供方
      }
      loaded.set(id, { def, ctx, instance, provided });
      log.record('kernel.load', { id });
      bus.emit('kernel:loaded', { id });
      return instance;
    })();

    inflight.set(id, task);
    try { return await task; } finally { inflight.delete(id); }
  }

  // ---- 卸载（先卸依赖方 → 逆序回滚副作用 → 摘能力）----
  // seen：防止循环依赖导致无限递归（a↔b）
  async function unuse(id, seen = new Set()) {
    if (seen.has(id)) return false;
    seen.add(id);
    if (!loaded.has(id)) return false;
    for (const [oid, o] of [...loaded]) {
      if (o.def.inject.includes(id)) await unuse(oid, seen);           // 依赖方先走
    }
    const { ctx, provided } = loaded.get(id);
    ctx.dispose();                                                     // 逆序回滚副作用
    for (const { name, prev, impl } of provided || []) {              // 摘能力：仅当自己仍是当前提供方
      if (container.get(name) !== impl) continue;                     // 同名已被后加载者覆盖 → 保持现状
      if (prev) container.provide(name, prev);                        // 恢复上一个提供方
      else container.remove(name);
    }
    loaded.delete(id);
    log.record('kernel.unload', { id });
    bus.emit('kernel:unloaded', { id });
    return true;
  }

  /** 装配：按配置一次装好一批插件（单一装配点） */
  async function assemble(ids) {
    for (const id of ids) await use(id);
    return [...loaded.keys()];
  }

  return { define, use, unuse, assemble, container, bus, security, permission, log,
           get loadedIds() { return [...loaded.keys()]; } };
}
