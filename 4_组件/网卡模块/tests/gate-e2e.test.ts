// gate-e2e.test.ts — 网卡门户端到端真实验证（插真网卡 + 真实联网，不 mock）
// 目标：回答"网卡门户到底有没有用"——用真实公网流量验证门面 fail-closed 与安全管道是否真正拦/放。
// 运行：node --experimental-strip-types tests/gate-e2e.test.ts
// 诚实披露：本测试真实访问公网（registry.npmmirror.com），需本机有外网。

import { net, NetworkForbidden } from '../src/net.ts';
import { NetworkBrick } from '../src/network.ts';
import { NetGuardError } from '../src/netguard.ts';

let pass = 0;
let fail = 0;
const failures: string[] = [];
function assert(cond: boolean, msg: string): void {
  if (cond) pass += 1;
  else { fail += 1; failures.push(msg); }
}

/** 捕捉请求抛出的错误类别：'forbidden'=门面拒 | 'netguard'=管道拒 | 'other'=其他(含网络层) | 'none'=未抛 */
function classify(err: unknown): string {
  if (err instanceof NetworkForbidden) return 'forbidden';
  if (err instanceof NetGuardError) return 'netguard';
  if (err instanceof Error) return 'other';
  return 'none';
}

async function main(): Promise<void> {
  // 前置：确保门面干净（无网卡）
  net.unregisterCard();

  // ── 1. 无网卡（fail-closed）：公网请求必须被拒 ──
  let cls = classify(await net.request('GET', 'https://registry.npmmirror.com/').catch(e => e));
  assert(cls === 'forbidden', `无网卡公网请求被拒(NetworkForbidden): 实际=${cls}`);

  // ── 2. 无网卡：回环也被拒（门面无执行器时连本地也禁） ──
  cls = classify(await net.request('GET', 'http://127.0.0.1:9/').catch(e => e));
  assert(cls === 'forbidden', `无网卡回环请求被拒(NetworkForbidden): 实际=${cls}`);

  // ── 3. 插真网卡（真实 fetch 执行器 + 安全管道） ──
  const brick = new NetworkBrick(); // 默认 createFetchExecutor + NetGuardPipeline
  assert(brick.isUp() === true, '插卡后 isCardPresent=true');

  // ── 4. 真实公网放行（npmmirror，真实 DNS + 真实 fetch） ──
  let ok = await net.request('GET', 'https://registry.npmmirror.com/').catch(e => e);
  assert(ok !== undefined && !(ok instanceof Error), '公网正常请求真实放行');

  // ── 5. 私网被拦（SSRF；192.168 在 DNS 校验前即拒） ──
  cls = classify(await net.request('GET', 'http://192.168.1.1/admin').catch(e => e));
  assert(cls === 'netguard', `私网 192.168.1.1 被 SSRF 拦截: 实际=${cls}`);

  // ── 6. 云 metadata 被拦 ──
  cls = classify(await net.request('GET', 'http://169.254.169.254/latest/meta-data/').catch(e => e));
  assert(cls === 'netguard', `云 metadata 端点被拦: 实际=${cls}`);

  // ── 7. 高危端口被拦 ──
  cls = classify(await net.request('GET', 'https://registry.npmmirror.com:3306/').catch(e => e));
  assert(cls === 'netguard', `高危端口 3306 被拦: 实际=${cls}`);

  // ── 8. 出站 DLP：body 带密钥必须被拦（不发真实请求） ──
  cls = classify(await net.request('POST', 'https://registry.npmmirror.com/api', { body: { token: 'sk-abcdefgh12345678' } }).catch(e => e));
  assert(cls === 'netguard', `出站 DLP 拦截带密钥 body: 实际=${cls}`);

  // ── 9. 回环放行：应到达"执行器层"而非被管道拦（连接层 ECONNREFUSED，属 other，非 netguard/forbidden） ──
  cls = classify(await net.request('GET', 'http://127.0.0.1:9/').catch(e => e));
  assert(cls === 'other', `回环放行到执行器层(连接失败而非守卫拦): 实际=${cls}`);

  // ── 10. 配额熔断（小配额真网卡；上传超限即拒） ──
  const brick2 = new NetworkBrick(undefined, { quotaBytes: 10, dlpLevel: 'off' });
  cls = classify(await net.request('POST', 'https://registry.npmmirror.com/api', { body: { data: 'x'.repeat(100) } }).catch(e => e));
  assert(cls === 'netguard', `配额熔断拦截超限上传: 实际=${cls}`);

  // ── 11. 黑名单：拒绝后同 URL 被拒（即使公网可达） ──
  const brick3 = new NetworkBrick();
  brick3.denyHost('registry.npmmirror.com');
  cls = classify(await net.request('GET', 'https://registry.npmmirror.com/').catch(e => e));
  assert(cls === 'netguard', `黑名单拦截公网域名: 实际=${cls}`);

  // ── 12. 白名单直放：skipDlp 豁免后带密钥 body 不再被管道拦，而是走到执行器层（真实 POST 公网返回 4xx，属 other） ──
  const brick4 = new NetworkBrick();
  brick4.allowHost('registry.npmmirror.com', { skipDlp: true });
  cls = classify(await net.request('POST', 'https://registry.npmmirror.com/api', { body: { token: 'sk-abcdefgh12345678' } }).catch(e => e));
  assert(cls === 'other', `per-host skipDlp 豁免后带密钥 body 放行到执行器(实际=${cls})`);

  // ── 13. 拔卡退化到 fail-closed ──
  brick.down();
  cls = classify(await net.request('GET', 'https://registry.npmmirror.com/').catch(e => e));
  assert(cls === 'forbidden', `拔卡后恢复 fail-closed: 实际=${cls}`);

  console.log(`\n=== 网卡门户端到端(真实联网) === pass=${pass} fail=${fail}${fail > 0 ? `\n失败项:\n${failures.map(f => ' - ' + f).join('\n')}` : ''}`);
  if (fail > 0) process.exit(1);
}

await main();