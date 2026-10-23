// net.ts — 网卡门面（唯一出网出口，fail-closed）
// 承接 palm 版 _core/net/__init__.py 语义：
//   - 本门面绝不 import 任何联网原语；联网能力仅由"网卡砖"注入执行器
//   - 无网卡注册 → 一切外网请求抛 NetworkForbidden（fail-closed）
//   - 本机回环（127.0.0.1/localhost/::1）不属外网出口，守卫放行（本地模型服务可用）
// 设计边界：门面只负责"是否允许出网 + 转发"，实际请求由注入的执行器完成。

export class NetworkForbidden extends Error {
  constructor(message = '无网卡注册，外网请求被拒（fail-closed）') {
    super(message);
    this.name = 'NetworkForbidden';
  }
}

export interface NetExecutor {
  execute(method: string, url: string, opts?: NetRequestOptions): Promise<unknown>;
}

export interface NetRequestOptions {
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
}

/** 判断 URL 是否本机回环（不属外网出口，守卫放行） */
function isLoopback(url: string): boolean {
  try {
    const u = new URL(url);
    return u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.hostname === '::1';
  } catch { return false; }
}

export class NetFacade {
  private executor: NetExecutor | null = null;

  /** 网卡砖注入执行器 */
  registerCard(exec: NetExecutor): void {
    this.executor = exec;
  }

  /** 拔出网卡（退化到 fail-closed） */
  unregisterCard(): void {
    this.executor = null;
  }

  get isCardPresent(): boolean { return this.executor !== null; }

  async request(method: string, url: string, opts: NetRequestOptions = {}): Promise<unknown> {
    // 回环放行（即便无网卡，本地服务也能通）
    if (isLoopback(url)) {
      if (!this.executor) throw new NetworkForbidden('回环地址但无执行器');
      return this.executor.execute(method, url, opts);
    }
    if (!this.executor) throw new NetworkForbidden();
    return this.executor.execute(method, url, opts);
  }
}

// 全局单例（网卡门面）
export const net = new NetFacade();