/**
 * 底层框架 · 边界测试
 * 覆盖：缺失 / 循环依赖 / 故障边界 / 依赖方先卸 / 热重插 /
 *       握手异常 / 权限吊销 / 副作用逆序回滚 / 并发加载。
 * 结果写 window.__test（供自动化断言）。
 */
import { createKernel } from './index.js';

const R = { checks: {}, notes: {} };
window.__test = R;
const eq = (name, cond) => { R.checks[name] = !!cond; };
const hasLog = (k, type) => k.log.all().some((e) => e.type === type);

(async () => {
  const k = await createKernel();

  // 1) 缺失插件 → 归一 null
  eq('missingReturnsNull', (await k.use('nope')) === null);
  eq('missingLogged', hasLog(k, 'kernel.missing'));

  // 2) 循环依赖 → 检测到、不死循环
  k.define('a', { inject: ['b'], setup: () => ({}) });
  k.define('b', { inject: ['a'], setup: () => ({}) });
  await k.use('a');
  eq('cycleDetected', hasLog(k, 'kernel.cycle'));
  await k.unuse('a'); await k.unuse('b');

  // 3) 故障边界：setup 抛错不崩
  k.define('boom', { provides: ['boom'], setup() { throw new Error('boom'); } });
  await k.use('boom');
  eq('setupThrowHandled', k.container.get('boom') === null);
  eq('setupErrorLogged', hasLog(k, 'kernel.setup.error'));
  await k.unuse('boom');

  // 4) 依赖方先卸载
  k.define('base', { provides: ['base'], setup: () => ({ base: { v: 1 } }) });
  k.define('leaf', { inject: ['base'], provides: ['leaf'], setup: () => ({ leaf: { v: 2 } }) });
  await k.assemble(['leaf']);
  eq('depAutoLoaded', k.loadedIds.includes('base') && k.loadedIds.includes('leaf'));
  await k.unuse('base');   // 卸 base → leaf 应先被卸
  eq('dependentsUnloadedFirst', !k.loadedIds.includes('leaf') && !k.loadedIds.includes('base'));

  // 5) 热重插
  await k.use('base');
  eq('replugWorks', k.container.get('base') !== null);

  // 6) 握手异常：无会话 / 篡改 saltId / 无会话校验
  eq('sealNoSessionNull', (await k.security.seal('ghost', 'x')) === null);
  const h = await k.security.seal('base', 'x');
  eq('sealOK', typeof h === 'string');
  eq('openWrongSalt', (await k.security.open(h.replace(/^base\.[^.]+/, 'base.WRONG'))) === null);
  eq('openNoSession', (await k.security.open('ghost.a.b.c')) === null);
  await k.unuse('base');

  // 7) 权限吊销 → ctx.use 被拒
  k.define('svc', { provides: ['svc'], setup: () => ({ svc: { hi: () => 1 } }) });
  k.permission.grant('use:svc');
  await k.use('svc');
  k.permission.revoke('use:svc');
  let gotSvc = null;
  k.define('user', { setup(ctx) { gotSvc = ctx.use('svc'); return {}; } });
  await k.use('user');
  eq('revokedUseDenied', gotSvc === null);
  await k.unuse('user'); await k.unuse('svc');

  // 8) 副作用逆序回滚
  const order = [];
  k.define('fx', { setup(ctx) { ctx.effect(() => order.push(1)); ctx.effect(() => order.push(2)); return {}; } });
  await k.use('fx');
  await k.unuse('fx');
  eq('effectsReverseOrder', JSON.stringify(order) === JSON.stringify([2, 1]));

  // 9) 并发加载 → 只 setup 一次
  let setups = 0;
  k.define('once', { setup() { setups++; return {}; } });
  await Promise.all([k.use('once'), k.use('once'), k.use('once')]);
  R.notes.concurrentSetups = setups;
  eq('concurrentUseOnce', setups === 1);

  R.logTypes = k.log.recent(60).map((e) => e.type);
  document.getElementById('out').textContent = JSON.stringify(R, null, 2);
  window.__testDone = true;
})().catch((e) => {
  R.error = String(e && e.stack ? e.stack : e);
  document.getElementById('out').textContent = 'ERROR\n' + R.error;
  window.__testDone = true;
});
