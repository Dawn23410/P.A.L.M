// network.ts — 网络砖（网卡砖：唯一持有联网原语 + 内置安全网关）
// 设计意图（对齐用户需求）：
//   "网络门面单独绑定个网络砖，而非绑 llm 的出入网" + "网络砖内置透明代理，拦截-验证-转发所有出入网请求"
// 分层：
//   net.ts       = 门面（fail-closed 判定 + 转发，绝不碰网络原语）
//   netguard.ts  = 安全管道（拦截-验证-转发：SSRF/私网拦截、出站 DLP、入站注入扫描、配额熔断）
//   network.ts   = 网卡砖（唯一持有 fetch；装载时经管道插卡，卸载时拔卡）
//   llm.ts / 工具 = 纯消费者（经 net.request 出网，摸不到执行器与管道内部）
// 参考：P.A.L.M 原版 palm_security/net.py（NetInterceptor 拦截代理 + _net_verdict 规则引擎）。

import { net, type NetExecutor, type NetRequestOptions } from './net.ts';
import { NetGuardPipeline, type NetGuardOptions, type HostPolicy } from './netguard.ts';

/** 网络砖能力接口 */
export interface NetBrick {
  isUp(): boolean;
  /** 拔卡（fail-closed；管道保留，可 up() 恢复） */
  down(): void;
  /** 恢复插卡 */
  up(): void;
  /** 管道策略快照（黑白名单/配额） */
  policySnapshot(): unknown;
  /** 主机白名单（可带豁免：skipDlp/skipIngress） */
  allowHost(h: string, policy?: HostPolicy): void;
  denyHost(h: string): void;
  /** 回环探活 */
  pingLoopback(url?: string): Promise<boolean>;
}

/** fetch 版裸执行器：网卡砖唯一持有（真正的联网原语） */
export function createFetchExecutor(): NetExecutor {
  return {
    async execute(method, url, opts = {}) {
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), opts.timeoutMs ?? 30_000);
      try {
        const r = await fetch(url, {
          method,
          headers: opts.headers,
          body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
          signal: ac.signal,
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
        return await r.json();
      } finally {
        clearTimeout(timer);
      }
    },
  };
}

/** 网卡砖实现：装载即构建安全管道并插卡（拦截-验证-转发） */
export class NetworkBrick implements NetBrick {
  readonly pipeline: NetGuardPipeline;
  private readonly handle: NetExecutor;

  constructor(executor: NetExecutor = createFetchExecutor(), guardOpts: NetGuardOptions = {}) {
    this.handle = executor;
    // 安全管道包裹裸执行器：所有出网先经 egress/ingress 验证
    this.pipeline = new NetGuardPipeline(executor, guardOpts);
    // 网卡砖把"管道化执行器"注入门面（唯一插卡点）
    net.registerCard(this.wrapped());
  }

  private wrapped(): NetExecutor {
    const p = this.pipeline;
    return {
      execute: (method, url, opts) => p.request(method, url, opts as NetRequestOptions),
    };
  }

  isUp(): boolean { return net.isCardPresent; }
  down(): void { net.unregisterCard(); }
  up(): void { net.registerCard(this.wrapped()); }

  policySnapshot(): unknown {
    return { ...this.pipeline.policy.snapshot(), quota: { used: this.pipeline.quota.used, limit: this.pipeline.quota.limit, fused: this.pipeline.quota.fused } };
  }
  allowHost(h: string, policy: HostPolicy = {}): void { this.pipeline.policy.allowHost(h, policy); }
  denyHost(h: string): void { this.pipeline.policy.denyHost(h); }

  async pingLoopback(url = 'http://127.0.0.1:11434/'): Promise<boolean> {
    try { await net.request('GET', url, { timeoutMs: 1500 }); return true; }
    catch { return false; }
  }
}

/** 网络砖 manifest 工厂 */
export function networkManifest() {
  return {
    bus: 'board' as const,
    isCore: true,
    enabled: true,
    capabilities: ['isUp', 'down', 'up', 'policySnapshot', 'allowHost', 'denyHost', 'pingLoopback'],
    description: '网卡砖：唯一持有联网原语；内置安全网关（拦截-验证-转发：SSRF拦截/DLP/注入扫描/配额）',
  };
}