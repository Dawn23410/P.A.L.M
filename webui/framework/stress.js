/**
 * 底层框架 · 压力 / 竞态 / 边界 测试（第二轮）
 * 覆盖：深链 / 菱形依赖 / 沙箱隔离 / 重握手 / 100 插件 / 日志上限 /
 *       并发 use-unuse 竞态 / 200 轮泄漏 / 同名服务冲突。
 */
import { createKernel, log } from './index.js';

const R = { checks: {}, notes: {} };
window.__stress = R;
const eq = (n, c) => { R.checks[n] = !!c; };
const ids = (k) => [...k.loadedIds].sort();

(async () => {
  // 1) 深链 5 级：加载顺序（依赖先行）与卸载（依赖方先走）
  {
    const k = await createKernel();
    const seq = [];
    const mk = (id, dep) => k.define(id, { inject: dep ? [dep] : [], setup() { seq.push(id); return {}; } });
    mk('e'); mk('d', 'e'); mk('c', 'd'); mk('b', 'c'); mk('a', 'b');
    await k.use('a');
    eq('deepChainLoadOrder', JSON.stringify(seq) === JSON.stringify(['e', 'd', 'c', 'b', 'a']));
    eq('deepChainLoaded', k.loadedIds.length === 5);
    await k.unuse('a');                                     // a 无依赖方 → 只卸 a
    eq('unloadLeafOnlySelf', JSON.stringify(ids(k)) === JSON.stringify(['b', 'c', 'd', 'e']));
    await k.unuse('e');                                     // e 是最深依赖 → 依赖方级联卸载
    eq('unloadRootCascadesAll', k.loadedIds.length === 0);
  }

  // 2) 菱形依赖 a→(b,c)→d：卸载 a 后 d 应保留（d 是依赖，不是依赖方）
  {
    const k = await createKernel();
    k.define('d', { setup: () => ({}) });
    k.define('b', { inject: ['d'], setup: () => ({}) });
    k.define('c', { inject: ['d'], setup: () => ({}) });
    k.define('a', { inject: ['b', 'c'], setup: () => ({}) });
    await k.use('a');
    eq('diamondLoaded', k.loadedIds.length === 4);
    await k.unuse('a');                                     // 只卸 a
    eq('diamondUnloadLeaf', JSON.stringify(ids(k)) === JSON.stringify(['b', 'c', 'd']));
    await k.unuse('b');                                     // 卸 b；d 仍被 c 依赖 → 保留
    eq('diamondKeepsSharedDep', JSON.stringify(ids(k)) === JSON.stringify(['c', 'd']));
  }

  // 3) 沙箱隔离：未授权能力访问不到；授权后可用
  {
    const k = await createKernel();
    k.define('secret', { provides: ['secret'], setup: () => ({ secret: { v: 42 } }) });
    await k.use('secret');
    let got = 'unset';
    k.define('spy', { setup(ctx) { got = ctx.use('secret'); return {}; } });
    await k.use('spy');
    eq('sandboxUnlistedDenied', got === null);          // 默认拒绝
    k.permission.grant('use:secret');
    let got2 = 'unset';
    k.define('spy2', { setup(ctx) { got2 = ctx.use('secret'); return {}; } });
    await k.use('spy2');
    eq('sandboxGrantedWorks', !!got2 && got2.v === 42);
  }

  // 4) 重握手使旧请求头失效；未知 id 拒绝
  {
    const k = await createKernel();
    k.define('m', { setup: () => ({}) });
    await k.use('m');
    const h1 = await k.security.seal('m', 'a');
    await k.security.handshake('m');                    // 重新握手 → 新盐
    eq('rehandshakeInvalidatesOldHeader', (await k.security.open(h1)) === null);
    const h2 = await k.security.seal('m', 'b');
    eq('newHeaderWorks', (await k.security.open(h2)) === 'b');
    eq('unknownIdRejected', (await k.security.open('zz.a.b.c')) === null);
  }

  // 5) 压力：100 插件并发装/卸
  {
    const k = await createKernel();
    for (let i = 0; i < 100; i++) k.define('p' + i, { provides: ['s' + i], setup: () => ({ ['s' + i]: { i } }) });
    await Promise.all([...Array(100).keys()].map((i) => k.use('p' + i)));
    eq('stress100Loaded', k.loadedIds.length === 100);
    await Promise.all([...Array(100).keys()].map((i) => k.unuse('p' + i)));
    eq('stress100Unloaded', k.loadedIds.length === 0 && k.container.names().length === 0);
  }

  // 6) 日志上限：>2000 事件丢最旧，seq 仍严格递增
  {
    for (let i = 0; i < 2100; i++) log.record('bulk', { i });
    const all = log.all();
    eq('logCap2000', all.length === 2000);
    let mono = true;
    for (let i = 1; i < all.length; i++) if (all[i].seq <= all[i - 1].seq) mono = false;
    eq('logMonotonicAfterCap', mono);
  }

  // 7) 并发 use/unuse 竞态：不崩且状态自洽
  {
    const k = await createKernel();
    k.define('r', { provides: ['r'], setup: () => ({ r: {} }) });
    let threw = false;
    try { await Promise.all([k.use('r'), k.use('r'), k.unuse('r'), k.use('r')]); }
    catch (e) { threw = true; }
    eq('raceNoThrow', !threw);
    eq('raceConsistent', (k.container.get('r') !== null) === k.loadedIds.includes('r'));
  }

  // 8) 泄漏：200 轮 use/unuse
  {
    const k = await createKernel();
    let hits = 0;
    k.define('leaky', { setup(ctx) { ctx.on('x', () => { hits++; }); return {}; } });
    for (let i = 0; i < 200; i++) { await k.use('leaky'); await k.unuse('leaky'); }
    k.bus.emit('x', 1);
    eq('noLeak200', hits === 0);
  }

  // 9) 同名服务冲突：卸载后提供方，应恢复上一个提供方（而非丢失）
  {
    const k = await createKernel();
    k.define('a', { provides: ['dup'], setup: () => ({ dup: { from: 'a' } }) });
    k.define('b', { provides: ['dup'], setup: () => ({ dup: { from: 'b' } }) });
    await k.use('a'); await k.use('b');
    R.notes.dupWinner = k.container.get('dup').from;
    await k.unuse('b');
    R.notes.dupAfterUnuseB = k.container.get('dup') ? k.container.get('dup').from : null;
    eq('dupRestoredAfterUnload', R.notes.dupAfterUnuseB === 'a');
  }

  // 10) 同名服务冲突（反向）：先卸载旧提供方，仍在线的新提供方能力不得被误删
  {
    const k = await createKernel();
    k.define('a', { provides: ['dup'], setup: () => ({ dup: { from: 'a' } }) });
    k.define('b', { provides: ['dup'], setup: () => ({ dup: { from: 'b' } }) });
    await k.use('a'); await k.use('b');            // 当前提供方 = b
    const bOnline = k.loadedIds.includes('b');
    await k.unuse('a');                             // 先卸旧的 a（b 仍在线）
    R.notes.dupAfterUnuseA = k.container.get('dup') ? k.container.get('dup').from : null;
    eq('dupKeptWhenUnloadingOldProvider', bOnline && R.notes.dupAfterUnuseA === 'b');
  }

  R.logTail = log.recent(10).map((e) => e.type);
  document.getElementById('out').textContent = JSON.stringify(R, null, 2);
  window.__stressDone = true;
})().catch((e) => {
  R.error = String(e && e.stack ? e.stack : e);
  document.getElementById('out').textContent = 'ERROR\n' + R.error;
  window.__stressDone = true;
});
