/**
 * LLM 内核 HTTP 客户端（前端唯一出口）
 * ====================================
 * 内核 FastAPI @ 127.0.0.1:10093，共 9 个端点（见 docs/内核适配与缺失UI清单.md）。
 * 规矩：**页面不直接 fetch 内核，一律走这里**，便于统一错误文案、
 * 统一超时、统一改地址，也让「哪些请求打到了内核」只有一个可审计的点。
 *
 * 出网路径：优先走框架 L0 的 security.net 门面（它会记审计日志），
 * 内核尚未 boot 完成时回落原生 fetch —— 门面是 fail-closed 的，
 * 需要应用层显式 allow(true)，这一步在这里集中做一次。
 */

export const KERNEL_BASE = 'http://127.0.0.1:10093';

/* 内核 GET /api/config 对已设置的 api_key 返回这个遮罩值；
   POST 时原样回传表示「不改动」，内核会自动回填磁盘上的真实 key。 */
export const KEY_MASK = '********';

/** 内核返回错误或不可达时抛这个，message 已是可以直接展示的中文 */
export class KernelError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'KernelError';
    this.status = status;
    this.payload = payload;
  }
}

/** 统一出口：框架安全门面 > 原生 fetch */
function net() {
  try {
    const k = typeof window !== 'undefined' ? window.__kernel : null;
    if (k && k.security && k.security.net && typeof k.security.net.fetch === 'function') {
      k.security.net.allow(true);
      return k.security.net;
    }
  } catch (e) { /* 门面不可用就走下面 */ }
  return { fetch: (url, opts) => fetch(url, opts) };
}

async function req(path, opts) {
  const init = opts || {};
  let res;
  try {
    res = await net().fetch(KERNEL_BASE + path, init);
  } catch (e) {
    throw new KernelError(
      '无法连接 LLM 内核（' + KERNEL_BASE + '）。请先启动：python -m palm_llm.server.api'
    );
  }
  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
  if (!res.ok) {
    // FastAPI 的错误体是 {detail: "..."}，discovery 层已把它翻译成中文
    const raw = data && (data.detail || data.message);
    const msg = raw ? (typeof raw === 'string' ? raw : JSON.stringify(raw))
                    : ('内核返回 HTTP ' + res.status);
    throw new KernelError(msg, res.status, data);
  }
  return data;
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/* ── 端点 ── */

/** 存活探针。返回 true/false，不抛异常（用于连接状态指示灯） */
export async function ping() {
  try { await req('/health'); return true; } catch (e) { return false; }
}

/** 读配置（api_key 已遮罩） */
export function getConfig() { return req('/api/config'); }

/** 写配置。body 形如 {config: AppConfig}；api_key 传遮罩值即保持原样 */
export function saveConfig(config) { return req('/api/config', json({ config })); }

/** 开销监控：请求数/错误数/耗时/per-provider/token 累计/RSS/CPU */
export function getMetrics() { return req('/metrics'); }

/** 会话列表 */
export function listConversations() { return req('/api/conversations'); }

/** 会话详情；不存在时内核返回 404 */
export function getConversation(cid) { return req('/api/conversations/' + encodeURIComponent(cid)); }

/** 删除会话 */
export function deleteConversation(cid) {
  return req('/api/conversations/' + encodeURIComponent(cid), { method: 'DELETE' });
}

/** 按协议探测上游并拉取模型列表，返回模型 id 数组 */
export async function discoverModels(providerType, baseUrl, apiKey) {
  const data = await req('/api/models/discover', json({
    provider_type: providerType || 'openai_compat',
    base_url: baseUrl,
    api_key: apiKey || '',
  }));
  const list = data && Array.isArray(data.models) ? data.models : [];
  if (!list.length) throw new KernelError('上游返回了空模型列表。', 200, data);
  return list;
}

/** 从任意 Ollama 地址提取根（去掉 /v1、/api 等尾缀）；空值回落本机 11434 */
export function ollamaRoot(baseUrl) {
  let s = String(baseUrl == null ? '' : baseUrl).trim();
  if (!s) return 'http://127.0.0.1:11434';
  s = s.replace(/\/+$/, '').replace(/\/v1$/i, '').replace(/\/api$/i, '');
  return s || 'http://127.0.0.1:11434';
}

/** 从 ollama /api/show 的 parameters 文本里取用户显式设置的上下文窗口 num_ctx */
function parseNumCtx(parameters) {
  const s = String(parameters == null ? '' : parameters);
  const m = s.match(/^\s*num_ctx\s+(\d+)\s*$/m);
  return m ? Number(m[1]) : null;
}

/**
 * 拉取本地 Ollama 的**模型详情**。
 * 分两步，因为两个端点的口径不同：
 *   GET  /api/tags  —— 批量；给的是 GGUF 的**架构上限** details.context_length
 *   POST /api/show  —— 单模型；parameters 里的 `num_ctx` 才是**用户设置的上限**
 * （实测 spark-x2.5:1.7b 架构上限 1M，但 Modelfile 里 PARAMETER num_ctx 131072，
 *   真正生效的是 128K —— 只查 /api/tags 会把 1M 当成用户设置，属于误读。）
 * 内核没有 ollama 详情代理端点，而 Ollama 默认对 localhost 放行 CORS，故前端直连，
 * 但仍走 security.net 门面，保持「出网只有一个口」。
 * @param {string} baseUrl Ollama 地址（通常 http://127.0.0.1:11434）
 * @returns {Promise<Object<string,{ctx:number|null,ctxMax:number|null,numCtx:number|null,
 *           capabilities:string[],parameterSize:string,quantization:string,family:string}>>}
 *   ctx = 生效上限（num_ctx 优先，缺省回落架构上限）
 */
export async function discoverOllamaInfo(baseUrl) {
  const root = ollamaRoot(baseUrl);
  let res;
  try {
    res = await net().fetch(root + '/api/tags', { method: 'GET' });
  } catch (e) {
    throw new KernelError('无法连接 Ollama（' + root + '）。请确认 `ollama serve` 正在运行。');
  }
  if (!res.ok) throw new KernelError('Ollama 返回 HTTP ' + res.status);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  const arr = data && Array.isArray(data.models) ? data.models : [];

  const out = {};
  await Promise.all(arr.map(async (m) => {
    const d = (m && m.details) || {};
    const key = m && (m.name || m.model);
    if (!key) return;
    const archCtx = Number(d.context_length) > 0 ? Number(d.context_length) : null;

    // 单模型查 num_ctx；某个模型失败不影响整张表
    let numCtx = null;
    try {
      const r2 = await net().fetch(root + '/api/show', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: key }),
      });
      if (r2.ok) {
        const s = await r2.json().catch(() => null);
        numCtx = parseNumCtx(s && s.parameters);
      }
    } catch (e) { /* 忽略：回落架构上限 */ }

    out[key] = {
      ctx: numCtx != null ? numCtx : archCtx,
      ctxMax: archCtx,
      numCtx: numCtx,
      capabilities: Array.isArray(m.capabilities) ? m.capabilities.slice() : [],
      parameterSize: d.parameter_size || '',
      quantization: d.quantization_level || '',
      family: d.family || '',
    };
  }));
  return out;
}

/* ── 配置结构工具（AppConfig 读写都靠这几个，避免各处自己摸字段）── */

/** 补齐内核 AppConfig 的必需字段，防止把残缺对象 POST 回去被 pydantic 拒 */
export function normalizeConfig(cfg) {
  const c = cfg && typeof cfg === 'object' ? cfg : {};
  return {
    providers: Array.isArray(c.providers) ? c.providers : [],
    active_provider: c.active_provider || '',
    active_model: c.active_model || '',
    system_prompt: typeof c.system_prompt === 'string' ? c.system_prompt : '你是一个有帮助的AI助手。',
    parameters: c.parameters && typeof c.parameters === 'object' ? c.parameters : {},
    presets: Array.isArray(c.presets) ? c.presets : [],
  };
}

/** 按 id 找 provider（用 hasOwnProperty 语义，不受原型链干扰） */
export function findProvider(cfg, id) {
  const list = (cfg && cfg.providers) || [];
  for (let i = 0; i < list.length; i++) {
    if (list[i] && list[i].id === id) return list[i];
  }
  return null;
}

/**
 * 把配置摊平成列表行：每个 provider 的每个 model 一行。
 * @returns {Array<{providerId, providerName, providerType, baseUrl, model, active}>}
 */
export function flattenModels(cfg) {
  const rows = [];
  const c = normalizeConfig(cfg);
  for (let i = 0; i < c.providers.length; i++) {
    const p = c.providers[i] || {};
    const models = Array.isArray(p.models) ? p.models : [];
    for (let j = 0; j < models.length; j++) {
      rows.push({
        providerId: p.id || '',
        providerName: p.name || p.id || '',
        providerType: p.type || 'openai_compat',
        baseUrl: p.base_url || '',
        model: models[j],
        active: p.id === c.active_provider && models[j] === c.active_model,
      });
    }
  }
  return rows;
}
