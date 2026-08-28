/**
 * P.A.L.M · API 统一配置
 * ────────────────────────────
 * 集中管理所有后端服务的地址、健康检查、以及 Mock 模式开关。
 */

/** 单个后端服务的配置 */
export interface ServiceConfig {
  name: string;
  baseUrl: string;
  healthEndpoint: string;
  /** 健康检查超时（毫秒） */
  healthTimeout: number;
  /**
   * 可选服务（如 GSV 语音模块）。
   * 默认不纳入全局健康轮询，避免该后端未启用时控制台刷出
   * ERR_CONNECTION_REFUSED 红字。设 VITE_ENABLE_GSV=true 后纳入轮询。
   */
  optional?: boolean;
}

/** 所有后端服务 */
export const SERVICES: Record<string, ServiceConfig> = {
  performance: {
    name: '性能监控',
    baseUrl: import.meta.env.VITE_PERF_API_BASE || 'http://127.0.0.1:8080',
    healthEndpoint: '/api/metrics',
    healthTimeout: 3000,
  },
  moduleManager: {
    name: '模块管理',
    baseUrl: import.meta.env.VITE_MODULE_API_BASE || 'http://127.0.0.1:9090',
    healthEndpoint: '/api/config',
    healthTimeout: 3000,
  },
  gptSoVits: {
    name: 'GPT-SoVITS API',
    baseUrl: import.meta.env.VITE_GSV_API_BASE || 'http://127.0.0.1:9880',
    healthEndpoint: '/status',
    healthTimeout: 5000,
    optional: import.meta.env.VITE_ENABLE_GSV !== 'true',
  },
  gptSoVitsRuntime: {
    name: 'GPT-SoVITS Runtime',
    baseUrl: import.meta.env.VITE_GSV_RUNTIME_BASE || 'http://127.0.0.1:5000',
    healthEndpoint: '/health',
    healthTimeout: 5000,
    optional: import.meta.env.VITE_ENABLE_GSV !== 'true',
  },
  cosyVoice: {
    name: 'CosyVoice API',
    baseUrl: import.meta.env.VITE_COSYVOICE_API_BASE || 'http://127.0.0.1:7861',
    healthEndpoint: '/health',
    healthTimeout: 5000,
  },
  llm: {
    name: 'LLM 对话 (Mock)',
    baseUrl: import.meta.env.VITE_LLM_API_BASE || 'http://127.0.0.1:8080',
    healthEndpoint: '/api/chat',
    healthTimeout: 3000,
    optional: true,
  },
  voskStt: {
    name: 'VOSK 离线 STT (WebSocket)',
    baseUrl: import.meta.env.VITE_VOSK_WS_URL || 'ws://127.0.0.1:2700',
    healthEndpoint: '/',
    healthTimeout: 2500,
    optional: true,
  },
};

/** 服务健康状态快照 */
export type ServiceHealthMap = Record<string, boolean>;

/** 全局 Mock 模式开关 — 可通过环境变量或运行时设置 */
let _forceMock = import.meta.env.VITE_FORCE_MOCK === 'true';

export function isForceMock(): boolean {
  return _forceMock;
}

export function setForceMock(val: boolean) {
  _forceMock = val;
}

// ─── 健康检查缓存 ────────────────────────────────────────────

let _healthCache: ServiceHealthMap = {};
let _lastCheck = 0;
const CACHE_TTL = 10_000; // 10 秒内复用缓存

/** 对单个服务执行健康检查 */
async function checkService(service: ServiceConfig): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), service.healthTimeout);
    const res = await fetch(`${service.baseUrl}${service.healthEndpoint}`, {
      signal: controller.signal,
    });
    clearTimeout(timer);
    return res.ok;
  } catch {
    return false;
  }
}

/** 检查所有（非可选）服务的可用性 */
export async function checkAllServices(): Promise<ServiceHealthMap> {
  const now = Date.now();
  if (now - _lastCheck < CACHE_TTL && Object.keys(_healthCache).length > 0) {
    return { ..._healthCache };
  }

  // 跳过 optional 服务（如未启用的 GSV），避免无谓的 ERR_CONNECTION_REFUSED。
  const entries = Object.entries(SERVICES).filter(([, s]) => !s.optional);
  const results = await Promise.allSettled(
    entries.map(([key]) => checkService(SERVICES[key])),
  );

  const map: ServiceHealthMap = {};
  entries.forEach(([key], i) => {
    map[key] = results[i].status === 'fulfilled' && (results[i] as PromiseFulfilledResult<boolean>).value;
  });

  _healthCache = map;
  _lastCheck = now;
  return map;
}

/** 判断某个服务是否可用（使用缓存） */
export async function isServiceAvailable(key: string): Promise<boolean> {
  if (isForceMock()) return false;
  const health = await checkAllServices();
  return !!health[key];
}

/** 获取某个服务的 baseUrl */
export function getBaseUrl(key: string): string {
  return SERVICES[key]?.baseUrl || '';
}
