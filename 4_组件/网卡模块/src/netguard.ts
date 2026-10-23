// netguard.ts — 网络安全管道（拦截 → 验证 → 转发）
// 设计参考（三方融合）：
//   1. P.A.L.M 原版 palm_security/net.py：NetInterceptor 透明代理 + _net_verdict 九条规则引擎
//      （硬否决→明确放行→边界→兜底，命中即停）+ PolicyStore 黑白名单 + Quota 双向配额熔断
//   2. SSRF 业界三道防线：域名黑白名单 → 发请求前真 DNS 解析（任一结果落私网即拒）→ 防 DNS rebinding
//   3. OWASP LLM Top10 2025（LLM01 间接提示注入）：入站注入模式扫描 + 出站 DLP
// 防御目标（用户指定）：
//   A. 外网恶意内容（SSRF/私网探测/恶意响应注入）
//   B. 用户本地敏感信息出网（DLP：密钥/密码/私钥；银行卡/身份证为 medium 级可选）
//   C. AI 新型攻击（间接提示注入经网页内容进入上下文）
// 管道：request → egressCheck(URL+body) → fetch(executor) → ingressCheck(response) → 返回
// 诚实披露：轻量版 DNS 校验后 fetch 仍会二次解析，不能完全防 DNS rebinding（完整方案需 pin IP 直连）。

import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import type { NetRequestOptions } from './net.ts';

// ── 裁决结果与类型化错误 ──
export type GuardAction = 'allow' | 'deny';
export interface GuardVerdict {
  action: GuardAction;
  /** 命中的规则（诊断/审计用） */
  rule: string;
  reason: string;
  /** 拒绝时关联的主机（供上层 ask 用户后 allowHost 放行） */
  host?: string;
}

/** 类型化拒绝：上层可程序化处理（审计/询问用户/白名单后重试，对应原版 allow_once 流程） */
export class NetGuardError extends Error {
  readonly verdict: GuardVerdict;
  constructor(verdict: GuardVerdict) {
    super(`[netguard:${verdict.rule}] ${verdict.reason}`);
    this.name = 'NetGuardError';
    this.verdict = verdict;
  }
}

// ── 私网/保留地址检测（对齐原版 _is_private_ip，补云元数据/CGNAT/IPv6 ULA/保留段） ──
export function isPrivateIp(ip: string): boolean {
  const v = isIP(ip);
  if (v === 4) {
    const p = ip.split('.').map(Number);
    if (p.length !== 4 || p.some(n => Number.isNaN(n) || n < 0 || n > 255)) return true;
    const [a, b] = p;
    if (a === 0 || a === 10 || a === 127) return true;                       // 0.0.0.0/8、10/8、回环
    if (a === 100 && b >= 64 && b <= 127) return true;                       // CGNAT 100.64/10
    if (a === 169 && b === 254) return true;                                 // link-local + 云 metadata
    if (a === 172 && b >= 16 && b <= 31) return true;                        // 172.16/12
    if (a === 192 && b === 168) return true;                                 // 192.168/16
    if (a === 198 && (b === 18 || b === 19)) return true;                    // benchmark
    if (a >= 224) return true;                                               // 组播 224/4 + 保留 240/4 + 广播
    return false;
  }
  if (v === 6) {
    const s = ip.toLowerCase();
    if (s === '::1' || s === '::') return true;                              // 回环/未指定
    if (s.startsWith('fe80')) return true;                                   // link-local
    if (s.startsWith('fc') || s.startsWith('fd')) return true;               // ULA fc00::/7
    return false;
  }
  return true; // 非法 IP 视为私网（fail-closed）
}

// ── DNS 解析缓存（同 host 60s 内复用，避免每请求 lookup） ──
const dnsCache = new Map<string, { ips: string[]; bad?: string; ok: boolean; ts: number }>();
const DNS_TTL_MS = 60_000;

function dnsCacheGet(host: string): { ok: boolean; ips: string[]; bad?: string } | null {
  const hit = dnsCache.get(host);
  if (hit && Date.now() - hit.ts < DNS_TTL_MS) return hit;
  dnsCache.delete(host);
  return null;
}

/** DNS 解析 + 全记录私网校验（SSRF 第二道防线：任一结果落私网即拒） */
export async function resolveAndCheckHost(host: string): Promise<{ ok: boolean; ips: string[]; bad?: string }> {
  // host 本身就是 IP
  if (isIP(host)) {
    return isPrivateIp(host) ? { ok: false, ips: [host], bad: host } : { ok: true, ips: [host] };
  }
  const cached = dnsCacheGet(host);
  if (cached) return cached;
  let result: { ok: boolean; ips: string[]; bad?: string };
  try {
    const records = await lookup(host, { all: true, verbatim: true });
    const ips = records.map(r => r.address);
    const badIp = ips.find(ip => isPrivateIp(ip));
    result = badIp ? { ok: false, ips, bad: badIp } : { ok: true, ips };
  } catch {
    result = { ok: false, ips: [], bad: 'DNS 解析失败（fail-closed）' };
  }
  // 仅缓存成功解析（失败的下次重试，网络恢复后不被 TTL 卡死）
  if (result.ok) dnsCache.set(host, { ...result, ts: Date.now() });
  return result;
}

// ── 校验位算法（消灭 DLP 数字误报：银行卡 Luhn、身份证 GB11643） ──
function luhnValid(digits: string): boolean {
  let sum = 0, alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48;
    if (d < 0 || d > 9) return false;
    if (alt) { d *= 2; if (d > 9) d -= 9; }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
}

function idCardValid(id: string): boolean {
  const W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
  const CODE = '10X98765432';
  let sum = 0;
  for (let i = 0; i < 17; i++) {
    const d = id.charCodeAt(i) - 48;
    if (d < 0 || d > 9) return false;
    sum += d * W[i];
  }
  return CODE[sum % 11] === id[17].toUpperCase();
}

// ── 出站 DLP（敏感信息不出网；对齐 DLP 内容识别引擎：关键字+正则+校验算法） ──
// 分级：high = 高置信凭据（默认拦）；medium = 低置信 PII（误报风险高，默认关、可开）
export type DlpLevel = 'high' | 'medium';

export function scanEgressBody(body: string, level: DlpLevel = 'high'): string | null {
  // high-1：私钥块（零误报）
  if (/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(body)) return '私钥块';
  // high-2：常见服务商 key 形态（sk-/pk-/rk- 前缀）
  if (/\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b/.test(body)) return 'API密钥';
  // high-3：凭据赋值（值需含数字/符号，纯单词如 "password: string" 不误报）
  const credAssign = body.match(/(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['"]?([^\s'"]{6,})/i);
  if (credAssign && /[0-9!@#$%^&*_\-+=]/.test(credAssign[1])) return '密码凭据';
  // high-4：UUID 紧跟 key/token/secret 语境
  if (/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b.{0,24}(?:key|token|secret)/i.test(body)) return 'API密钥';

  if (level === 'medium') {
    // medium-1：银行卡（正则 + Luhn 校验位，订单号/时间戳不再误报）
    for (const m of body.matchAll(/\b\d{13,19}\b/g)) {
      if (luhnValid(m[0])) return '银行卡';
    }
    // medium-2：身份证（18 位 + GB11643 校验位）
    for (const m of body.matchAll(/\b\d{17}[\dXx]\b/g)) {
      if (idCardValid(m[0])) return '身份证';
    }
    // medium-3：内网拓扑描述
    if (/(?:内网|局域网|intranet).{0,12}(?:ip|地址|拓扑)/i.test(body)) return '内网拓扑';
  }
  return null;
}

// ── 入站提示注入扫描（OWASP LLM01：间接注入经外部内容入上下文） ──
export function scanIngressBody(body: string): string | null {
  if (/ignore (?:all )?(?:previous|prior|above) (?:instructions|prompts|rules)/i.test(body)) return '英文覆盖指令';
  if (/you are now (?:a|an|the) |disregard your (?:rules|training)/i.test(body)) return '英文角色劫持';
  if (/忽略(?:之前|上面|以上|先前)(?:的)?(?:所有)?(?:指令|提示|规则|设定)/.test(body)) return '中文覆盖指令';
  if (/(?:从现在起|现在开始)你(?:是|变成)(?:一个)?/.test(body)) return '中文角色劫持';
  if (/(?:system prompt|系统提示词|初始指令|系统设定).{0,8}(?:输出|打印|泄露|reveal|show|print)/i.test(body)) return '系统提示词窃取';
  if (/(?:print|show|reveal|display|输出|打印|泄露).{0,16}(?:system prompt|系统提示词|初始指令|系统设定)/i.test(body)) return '系统提示词窃取';
  if (/(?:执行|运行|调用).{0,10}(?:删除|格式化|rm\s+-rf|format\s+c:)/i.test(body)) return '工具滥用指令';
  return null;
}

// ── 流量配额（对齐原版 Quota：上传+下载双向计费，超限熔断） ──
export class Quota {
  used = 0;
  fused = false;
  readonly limit: number;
  constructor(limit = 20 * 1024 * 1024) { // 20MB 默认
    this.limit = limit;
  }
  add(n: number): void {
    if (this.fused) return;
    this.used += n;
    if (this.limit > 0 && this.used >= this.limit) this.fused = true;
  }
  reset(): void { this.used = 0; this.fused = false; }
}

// ── 主机策略（对齐原版 PolicyStore + per-host 豁免） ──
export interface HostPolicy {
  /** 跳过出站 DLP（信任的 host，用户主动处理含敏感词内容时用） */
  skipDlp?: boolean;
  /** 跳过入站注入扫描（信任的站点，如安全研究文章站） */
  skipIngress?: boolean;
}

export class PolicyStore {
  private allow = new Map<string, HostPolicy>();
  private deny = new Set<string>();
  verdictFor(host: string): 'allow' | 'deny' | null {
    const h = normHost(host);
    if (this.deny.has(h)) return 'deny';
    if (this.allow.has(h)) return 'allow';
    return null;
  }
  policyFor(host: string): HostPolicy | undefined {
    return this.allow.get(normHost(host));
  }
  allowHost(h: string, policy: HostPolicy = {}): void { this.allow.set(normHost(h), policy); }
  denyHost(h: string): void { this.deny.add(normHost(h)); }
  snapshot(): { allow: string[]; deny: string[] } {
    return { allow: [...this.allow.keys()], deny: [...this.deny] };
  }
}

function normHost(h: string): string {
  return h.toLowerCase().replace(/\.$/, '');
}

// ── 配置 ──
export interface NetGuardOptions {
  /** 出站 DLP 级别：high（默认，只拦高置信凭据）/ medium（加银行卡/身份证）/ off */
  dlpLevel?: DlpLevel | 'off';
  /** 入站注入扫描开关（默认开） */
  ingressScan?: boolean;
  /** 私网/SSRF 拦截开关（默认开；回环与白名单除外） */
  ssrfGuard?: boolean;
  /** 流量配额字节，上传+下载双向（默认 20MB；0=不限） */
  quotaBytes?: number;
  /** 扫描字符上限（超过不扫防 DoS；默认 200 万字符） */
  maxScanChars?: number;
}

export const DEFAULT_GUARD_OPTIONS: Required<NetGuardOptions> = {
  dlpLevel: 'high',
  ingressScan: true,
  ssrfGuard: true,
  quotaBytes: 20 * 1024 * 1024,
  maxScanChars: 2_000_000,
};

// ── 安全管道：拦截 → 验证 → 转发 ──
export class NetGuardPipeline {
  readonly policy = new PolicyStore();
  readonly quota: Quota;
  private readonly raw: import('./net.ts').NetExecutor;
  private readonly opts: Required<NetGuardOptions>;

  constructor(raw: import('./net.ts').NetExecutor, opts: NetGuardOptions = {}) {
    this.raw = raw;
    this.opts = { ...DEFAULT_GUARD_OPTIONS, ...opts };
    this.quota = new Quota(this.opts.quotaBytes);
  }

  /** 出站验证（转发前）：双向计费 + 白名单直放 + URL 规则 + 私网 SSRF + 出站 DLP */
  async egressCheck(method: string, url: string, body?: unknown): Promise<GuardVerdict> {
    let u: URL;
    try { u = new URL(url); } catch {
      return { action: 'deny', rule: 'URL', reason: '非法 URL' };
    }

    // 0) 黑白名单（对齐原版：deny 优先；allow 显式白名单直放，免 DNS 校验）
    const policyV = this.policy.verdictFor(u.hostname);
    if (policyV === 'deny') {
      return { action: 'deny', rule: '黑名单', reason: `主机 ${u.hostname} 在黑名单`, host: u.hostname };
    }

    // 上传出站计费（对齐原版 Quota 双向）
    if (body !== undefined) this.quota.add(JSON.stringify(body).length);
    if (this.quota.fused) {
      return { action: 'deny', rule: '配额熔断', reason: `流量超限 ${this.quota.limit}B`, host: u.hostname };
    }

    // 白名单直放（跳过 SSRF/DLP；注入扫描仍按 per-host 策略）
    if (policyV === 'allow') {
      return { action: 'allow', rule: '白名单', reason: `主机 ${u.hostname} 显式放行` };
    }

    // 1) 高危端口硬否决（原版规则2）
    const port = u.port ? Number(u.port) : (u.protocol === 'https:' ? 443 : 80);
    if (HIGH_RISK_PORTS.has(port)) {
      return { action: 'deny', rule: '高危端口', reason: `端口 ${port} 被禁（管理/DB/远程）`, host: u.hostname };
    }

    // 2) 私网/SSRF：回环放行（本地模型服务），其余私网拒（含云 metadata）
    if (this.opts.ssrfGuard) {
      const loopback = u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.hostname === '::1';
      if (!loopback) {
        const r = await resolveAndCheckHost(u.hostname);
        if (!r.ok) {
          return { action: 'deny', rule: 'SSRF私网', reason: `解析到私网/保留地址 ${r.bad ?? ''}`, host: u.hostname };
        }
      }
    }

    // 3) 出站 DLP：body 敏感信息不出网（分级，high 默认）
    if (this.opts.dlpLevel !== 'off' && body !== undefined) {
      const hp = this.policy.policyFor(u.hostname);
      if (!hp?.skipDlp) {
        const text = typeof body === 'string' ? body : JSON.stringify(body);
        if (text.length <= this.opts.maxScanChars) {
          const hit = scanEgressBody(text, this.opts.dlpLevel);
          if (hit) return { action: 'deny', rule: `DLP:${hit}`, reason: `出站内容含${hit}，阻断`, host: u.hostname };
        }
      }
    }

    return { action: 'allow', rule: 'pass', reason: '出站验证通过' };
  }

  /** 入站验证（转发后）：配额 + 注入扫描（per-host 豁免） */
  ingressCheck(payload: unknown, host?: string): GuardVerdict {
    // 下载计费（双向对齐原版）
    const text = typeof payload === 'string' ? payload : JSON.stringify(payload ?? '');
    this.quota.add(text.length);
    if (this.quota.fused) {
      return { action: 'deny', rule: '配额熔断', reason: `流量超限 ${this.quota.limit}B`, host };
    }

    if (this.opts.ingressScan) {
      const hp = host ? this.policy.policyFor(host) : undefined;
      if (!hp?.skipIngress && text.length <= this.opts.maxScanChars) {
        const hit = scanIngressBody(text);
        if (hit) return { action: 'deny', rule: `注入:${hit}`, reason: `响应含${hit}模式，阻断进入上下文`, host };
      }
    }
    return { action: 'allow', rule: 'pass', reason: '入站验证通过' };
  }

  /** 完整管道：拦截 → egress 验证 → raw 转发 → ingress 验证；拒绝抛 NetGuardError（可程序化处理） */
  async request(method: string, url: string, opts: NetRequestOptions = {}): Promise<unknown> {
    const eg = await this.egressCheck(method, url, opts.body);
    if (eg.action === 'deny') throw new NetGuardError(eg);
    const resp = await this.raw.execute(method, url, opts);
    const host = safeHost(url);
    const ig = this.ingressCheck(resp, host);
    if (ig.action === 'deny') throw new NetGuardError(ig);
    return resp;
  }
}

function safeHost(url: string): string | undefined {
  try { return new URL(url).hostname; } catch { return undefined; }
}

// 高危端口表（原版规则2 + Node 生态常见服务）
const HIGH_RISK_PORTS = new Set([22, 23, 445, 3306, 3389, 5900, 6379, 27017]);