/**
 * 测试项目：跑在底层框架上的迷你聊天 App
 * ======================================
 * 插件与依赖链：ui(页面) → chat → storage(硬依赖) / model(软依赖，按调用取)
 * 另有 metrics 插件订阅事件。
 * 暴露 window.__app 供自动化动态测试驱动。
 */
import { createKernel } from '../index.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function createApp() {
  const k = await createKernel();
  window.__probeCount = 0;   // 泄漏探针计数

  // ---- 插件定义（单一装配点）----

  k.define('storage', {
    provides: ['storage'],
    setup() {
      const m = new Map();
      return { storage: { set: (a, b) => m.set(a, b), get: (a) => m.get(a) ?? null, size: () => m.size } };
    },
  });

  k.define('model', {
    provides: ['model'],
    setup() {
      return {
        model: {
          async *stream(text) {
            const out = '收到：' + text;
            for (const ch of out) { await sleep(12); yield ch; }
          },
        },
      };
    },
  });

  k.define('chat', {
    inject: ['storage'],          // 硬依赖：storage 卸载 → chat 随之卸载
    provides: ['chat'],
    setup(ctx) {
      const history = [];
      ctx.on('probe', () => { window.__probeCount++; });   // 泄漏探针（可逆订阅）
      return {
        chat: {
          history,
          async send(text, onToken) {
            const model = ctx.use('model');    // 软依赖：按调用取（可被热插拔/降级）
            const storage = ctx.use('storage');// 按调用取（权限可被运行时吊销）
            let acc = '';
            if (model) { for await (const t of model.stream(text)) { acc += t; onToken && onToken(acc); } }
            else { acc = '(模型不可用，已降级)'; onToken && onToken(acc); }
            history.push({ role: 'user', text }, { role: 'assistant', text: acc });
            if (storage) storage.set('history', history);   // 无权限 → 跳过（降级）
            ctx.emit('chat:reply', { text: acc });
            return acc;
          },
        },
      };
    },
  });

  k.define('metrics', {
    provides: ['metrics'],
    setup(ctx) {
      let replies = 0;
      ctx.on('chat:reply', () => { replies++; });
      return { metrics: { replies: () => replies } };
    },
  });

  // ---- 授权 ----
  ['storage', 'model', 'chat', 'metrics'].forEach((n) => k.permission.grant('use:' + n));

  // ---- 装配（chat 自动带上 storage；model 单独装）----
  await k.assemble(['chat', 'metrics', 'model']);

  return { k };
}
