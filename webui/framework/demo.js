/**
 * 底层框架 · 演示
 * ================
 * 演示：装配 → 能力注入 → 握手鉴权 → 热插拔回滚。
 * 结果写入 #out 与 window.__demo（供自动化测试断言）。
 */
import { createKernel } from './index.js';

const report = { ok: {}, steps: [] };
window.__demo = report;

const countLog = (k, type) => k.log.all().filter((e) => e.type === type).length;

(async () => {
  const k = await createKernel();

  // ---- 单一装配点：定义插件（唯一出现"注册"的地方）----
  k.define('storage', {
    provides: ['storage'],
    setup(ctx) {
      const map = new Map();
      ctx.log('plugin.setup', { plugin: 'storage' });
      return { storage: { set: (key, v) => map.set(key, v), get: (key) => map.get(key) ?? null } };
    },
  });

  k.define('greeter', {
    inject: ['storage'],
    provides: ['greeter'],
    setup(ctx) {
      const storage = ctx.use('storage');               // 能力注入（白名单 + 权限）
      const timer = setInterval(() => {}, 1000);         // 副作用①：定时器
      ctx.effect(() => clearInterval(timer));            //   → 可逆
      ctx.on('ping', (p) => ctx.log('greeter.pong', { p })); // 副作用②：事件订阅 → 可逆
      ctx.log('plugin.setup', { plugin: 'greeter', hasStorage: !!storage });
      return {
        greeter: {
          greet: (name) => { storage.set('last', name); return `hi ${name}`; },
          last: () => storage.get('last'),
        },
      };
    },
  });

  // ---- 授权（L0-权限）----
  k.permission.grant('use:storage');
  k.permission.grant('use:greeter');

  // ---- 装配（自动带上依赖 storage）----
  await k.assemble(['greeter']);
  report.ok.loaded = [...k.loadedIds].sort();

  // ---- 服务容器（缺失归一 null）----
  const greeter = k.container.get('greeter');
  report.ok.greet = greeter.greet('PALM');
  report.ok.last = greeter.last();
  report.ok.missingService = k.container.get('nope') === null;

  // ---- 握手鉴权 + 加密信息头 ----
  const header = await k.security.seal('greeter', 'hello');
  report.ok.headerShape = /^greeter\.[\w+/=]+\./.test(header);
  report.ok.openOK = (await k.security.open(header)) === 'hello';
  const tampered = header.replace(/\.[^.]+$/, '.AAAA');
  report.ok.openTamperedRejected = (await k.security.open(tampered)) === null;   // 篡改 → 拒

  // ---- 权限默认拒绝 ----
  report.ok.defaultDeny = k.permission.check('use:never-granted') === false;

  // ---- 订阅生效 ----
  const p0 = countLog(k, 'greeter.pong');
  k.bus.emit('ping', 1);
  report.ok.subscriptionWorks = countLog(k, 'greeter.pong') === p0 + 1;

  // ---- 热插拔：卸载 greeter，副作用应回滚 ----
  const p1 = countLog(k, 'greeter.pong');
  await k.unuse('greeter');
  k.bus.emit('ping', 2);
  report.ok.afterUnload = {
    serviceGone: k.container.get('greeter') === null,          // 能力已摘除
    subscriptionRolledBack: countLog(k, 'greeter.pong') === p1, // 订阅已退订
    loaded: [...k.loadedIds],
  };
  report.ok.storageStillThere = k.container.get('storage') !== null;   // 未依赖它的不受影响

  report.logTypes = k.log.recent(30).map((e) => e.type);

  const out = document.getElementById('out');
  if (out) out.textContent = JSON.stringify(report, null, 2);
  window.__demoDone = true;
})().catch((e) => {
  report.error = String(e && e.stack ? e.stack : e);
  const out = document.getElementById('out');
  if (out) out.textContent = 'ERROR\n' + report.error;
  window.__demoDone = true;
});
