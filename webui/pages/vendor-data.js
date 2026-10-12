/**
 * 供应商与模型能力数据表
 * ======================
 * **能力部分不自建，直接消费内核档案的自动生成镜像 kernel-profiles.js。**
 * 之前这里是一张手写的调研表，与内核真实数据冲突（例：GLM-5.3 内核是
 * low/high/max，手写表写成低/中/高），且模型名随厂商迭代很快过时。
 * 现在唯一事实来源是内核的 palm_llm/providers/_profiles_data.py。
 *
 * 本文件只保留内核没有建模的部分：
 *   - 供应商预设（label / short / 默认协议 / 默认端点）—— 纯 UI 关注点
 *   - 「工具调用」能力 —— 内核档案未声明该维度
 *   - 非对话模型（embedding / 语音 / 图像生成）的前端拦截
 * model-modal.js（弹窗）与 models.js（设置页模型列表）共用。
 */

import { KERNEL_PROFILES, DOMAIN_HINTS, isBlank } from './kernel-profiles.js';
import { resolveOllamaModel, versionHint as ollamaVersionHint } from './ollama-info.js';

/* ── 供应商预设 ──
 * 预设供应商：协议与地址整套跟随预设、界面灰色禁填；「自定义」放开手动填写。 */
export const VENDORS = {
  /* 国内主流（均 OpenAI 兼容） */
  deepseek:   { label: 'DeepSeek 深度求索', short: 'DeepSeek',      type: 'openai_compat', base: 'https://api.deepseek.com/v1',                            group: 'cn' },
  zhipu:      { label: '智谱 GLM',          short: '智谱 GLM',       type: 'openai_compat', base: 'https://open.bigmodel.cn/api/paas/v4',                   group: 'cn' },
  qwen:       { label: '通义千问 Qwen',     short: '通义千问',       type: 'openai_compat', base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',      group: 'cn' },
  kimi:       { label: 'Kimi 月之暗面',     short: 'Kimi',           type: 'openai_compat', base: 'https://api.moonshot.cn/v1',                             group: 'cn' },
  doubao:     { label: '豆包 火山方舟',     short: '豆包',           type: 'openai_compat', base: 'https://ark.cn-beijing.volces.com/api/v3',               group: 'cn' },
  minimax:    { label: 'MiniMax',           short: 'MiniMax',        type: 'openai_compat', base: 'https://api.minimax.cn/v1',                            group: 'cn' },
  stepfun:    { label: '阶跃星辰 Step',     short: '阶跃星辰',       type: 'openai_compat', base: 'https://api.stepfun.com/v1',                             group: 'cn' },
  hunyuan:    { label: '腾讯混元',          short: '腾讯混元',       type: 'openai_compat', base: 'https://api.hunyuan.cloud.tencent.com/v1',               group: 'cn' },
  spark:      { label: '讯飞星火',          short: '讯飞星火',       type: 'openai_compat', base: 'https://spark-api-open.xf-yun.com/v1',                   group: 'cn' },
  baichuan:   { label: '百川智能',          short: '百川',           type: 'openai_compat', base: 'https://api.baichuan-ai.com/v1',                         group: 'cn' },
  /* 国外主流 */
  openai:     { label: 'OpenAI',            short: 'OpenAI',         type: 'openai_compat', base: 'https://api.openai.com/v1',                              group: 'global' },
  anthropic:  { label: 'Anthropic Claude',  short: 'Anthropic',      type: 'anthropic',     base: 'https://api.anthropic.com',                              group: 'global' },
  gemini:     { label: 'Google Gemini',     short: 'Google',         type: 'gemini',        base: 'https://generativelanguage.googleapis.com',              group: 'global' },
  xai:        { label: 'xAI Grok',          short: 'xAI',            type: 'openai_compat', base: 'https://api.x.ai/v1',                                    group: 'global' },
  mistral:    { label: 'Mistral',           short: 'Mistral',        type: 'openai_compat', base: 'https://api.mistral.ai/v1',                              group: 'global' },
  /* 聚合 / 本地 / 自定义 */
  nonelinear: { label: '非线智能 NoneLinear', short: '非线智能',     type: 'openai_compat', base: 'https://api.nonelinear.com.cn/v1',                       group: 'agg' },
  ollama:     { label: 'Ollama 本地',       short: 'Ollama',         type: 'ollama',        base: 'http://127.0.0.1:11434',                                 group: 'agg' },
  custom:     { label: '自定义',            short: '自定义',         type: 'openai_compat', base: '',                                                       group: 'agg' },
};

export const GROUPS = [
  { key: 'cn',     label: '国内主流' },
  { key: 'global', label: '国外主流' },
  { key: 'agg',    label: '聚合 / 本地' },
];

/* 协议 = LLM 内核 providers 目录实际支持的四条通道 */
export const PROTOCOLS = [
  { key: 'openai_compat', label: 'OpenAI 兼容' },
  { key: 'anthropic',     label: 'Anthropic 原生' },
  { key: 'gemini',        label: 'Gemini 原生' },
  { key: 'ollama',        label: 'Ollama 原生' },
];

/* ── 思考挡位 ──
 * 词汇表取自内核档案实际出现过的取值全集（7 档），顺序即强度递增。
 * 每个模型允许哪些档位由内核规则决定，前端不再自己编一套阶梯：
 *   OpenAI gpt-5.x / o 系、豆包 seed-2-1 → 全部 7 档
 *   Claude opus-4.7/5、sonnet-5          → low/medium/high/xhigh/max（5）
 *   GLM-5.3、Kimi-K3、DeepSeek-v4-pro    → low/high/max（3，无 medium）
 *   DeepSeek-v4-flash                    → low/high（2）
 * 「一个挡位一个勾选框」、可多选。 */
export const THINK_LEVELS = [
  { key: 'none',    label: '可关闭', hint: '可以完全关掉推理，响应最快' },
  { key: 'minimal', label: '极低', hint: '极少量推理，几乎不增加延迟' },
  { key: 'low',     label: '低',   hint: '较快、较省 token' },
  { key: 'medium',  label: '中',   hint: '速度与质量均衡' },
  { key: 'high',    label: '高',   hint: '推理较充分' },
  { key: 'xhigh',   label: '极高', hint: '推理很充分，明显更慢' },
  { key: 'max',     label: '最高', hint: '最大推理预算，最慢' },
];

const THINK_LABEL = {};
THINK_LEVELS.forEach(function (t) { THINK_LABEL[t.key] = t.label; });

/* 思考模式标签后缀：常开 / 常关 / 开关式，比笼统的「深度思考」信息量大 */
const THINK_SUFFIX = {
  always_on: '（常开）',
  always_off: '（常关）',
  toggle: '（开关式）',
  unsupported: '（不支持）',
};

/* ── 供应商键 → 内核 Profile 名的别名 ──
 * 前端预设比内核多（18 vs 10）：内核档案只覆盖 deepseek / glm / qwen / kimi /
 * doubao / hunyuan / openai / anthropic / gemini 九家加 generic。其余
 * （xai / mistral / minimax / stepfun / spark / baichuan / 非线 / ollama / 自定义）
 * 在核心里没有档案，会回落 generic，即「思考能力未知」。
 * 这是内核待补的缺口，不是前端可以自行编造的。 */
const VENDOR_PROFILE_ALIAS = {
  zhipu: 'glm',
};

/* 内核档案没建模「非对话模型」：embedding / 语音 / 图像生成都不该进对话列表。
   显式清零，防止 Profile 默认能力残留。 */
const NO_CHAT = { reasoning: 0, tools: 0, files: 0, vision: 0 };
const NON_CHAT_RE = /embedding|rerank|whisper|tts|dall-e|moderation|stable-diffusion/i;

/* 内核档案也未声明「工具调用」能力，前端保持宽松默认：只关掉已知不支持的老模型 */
const NO_TOOLS_RE = /^gpt-3|^gpt-4|baichuan3|abab5/i;

/** 只取对象自有属性，避免 __proto__ / constructor 等原型链键被当成配置 */
function own(map, key) {
  if (typeof key !== 'string') return undefined;
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined;
}

/* ── 一级匹配：显式供应商 ＞ 端点域名特征 ＞ generic（对齐内核 _resolve_profile）── */
export function resolveProfile(vendor, baseUrl) {
  const vk = typeof vendor === 'string' ? vendor.trim().toLowerCase() : '';
  const alias = own(VENDOR_PROFILE_ALIAS, vk) || vk;
  if (own(KERNEL_PROFILES, alias)) return KERNEL_PROFILES[alias];
  const host = String(baseUrl || '').toLowerCase();
  for (let i = 0; i < DOMAIN_HINTS.length; i++) {
    if (host.indexOf(DOMAIN_HINTS[i][0]) >= 0) {
      return own(KERNEL_PROFILES, DOMAIN_HINTS[i][1]) || KERNEL_PROFILES.generic;
    }
  }
  return KERNEL_PROFILES.generic;
}

/* ── 二级匹配：model 全串匹配，priority 降序取首条命中（对齐内核 _match_rule）──
 * 内核用 re.fullmatch，JS 没有对应 API，用 ^(?:...)$ 等效锚定。
 * 命中语义很关键：glm-5.3-flash 不会被 glm-5\.3 吃掉，因为前者 priority 更高。 */
const RE_CACHE = new Map();

function patternRe(pattern) {
  let re = RE_CACHE.get(pattern);
  if (re === undefined) {
    try { re = new RegExp('^(?:' + pattern + ')$'); } catch (e) { re = null; }
    RE_CACHE.set(pattern, re);
  }
  return re;
}

export function matchRule(profile, model) {
  const id = String(model == null ? '' : model).toLowerCase();
  const rules = (profile && profile.rules) || [];
  const sorted = rules.slice().sort(function (a, b) { return (b.priority || 0) - (a.priority || 0); });
  for (let i = 0; i < sorted.length; i++) {
    const re = patternRe(sorted[i].pattern);
    if (re && re.test(id)) return sorted[i];
  }
  return null;   // 未命中回落 Profile，且不报错（内核口径）
}

/* ModelRule 只对非空字段覆盖 Profile（对齐内核 _MERGE_FIELDS） */
const MERGE_FIELDS = [
  'reasoningKeys', 'thinkingParam', 'needsReasoningEcho', 'stopSemantics',
  'requireUsageOption', 'vendorParams', 'maxOutput', 'supportsVision',
  'docMimes', 'maxFileMb', 'rejectForcedTool', 'rejectDocuments',
];

function mergeProfile(profile, rule) {
  const out = {};
  for (const k in profile) if (Object.prototype.hasOwnProperty.call(profile, k)) out[k] = profile[k];
  if (!rule) return out;
  for (let i = 0; i < MERGE_FIELDS.length; i++) {
    const f = MERGE_FIELDS[i];
    if (!isBlank(rule[f])) out[f] = rule[f];
  }
  return out;
}

/**
 * 推断某个「供应商 × 模型」的完整能力（内核档案驱动）。
 * @param {string} vendor  供应商键（VENDORS 的键）
 * @param {string} model   模型 id
 * @param {string} [baseUrl] 端点地址，用于域名特征回落
 * @returns {{features: object, levels: string[], thinking: (string|undefined), rule: object|null}}
 *   features: { reasoning, levels, thinkLevels, tools, files, vision }
 *   thinking: always_on / always_off / toggle / unsupported / undefined
 */
export function inferCapability(vendor, model, baseUrl) {
  const profile = resolveProfile(vendor, baseUrl);
  const rule = matchRule(profile, model);
  const eff = mergeProfile(profile, rule);

  const id = String(model == null ? '' : model);

  if (NON_CHAT_RE.test(id)) {
    const nc = {};
    for (const k in NO_CHAT) nc[k] = NO_CHAT[k];
    nc.levels = false;
    nc.thinkLevels = [];
    return { features: nc, levels: [], thinking: 'unsupported', rule: rule };
  }

  const levels = (rule && Array.isArray(rule.effortAllowed)) ? rule.effortAllowed.slice() : [];
  const thinking = (rule && rule.thinking) ? rule.thinking : undefined;
  const canThink = thinking !== 'unsupported';
  // 有档位、或明确是常开/开关式思考 → 视为具备深度思考
  const hasThinking = canThink && (levels.length > 0 || thinking === 'always_on' || thinking === 'toggle');
  // 文档：Profile 声明了能吃的 MIME 且没有整家拒绝文档
  const files = !eff.rejectDocuments && (eff.docMimes || []).length > 0;

  const features = {
    reasoning: hasThinking,
    levels: levels.length > 0,
    thinkLevels: levels,
    tools: !NO_TOOLS_RE.test(id),
    files: files,
    vision: !!eff.supportsVision,
  };
  return { features: features, levels: levels, thinking: thinking, rule: rule };
}

/** 只要功能位（含派生的 levels / thinkLevels） */
export function inferFeatures(vendor, model, baseUrl) {
  return inferCapability(vendor, model, baseUrl).features;
}

/* ── ollama 专用解析 ──
 * 内核档案没有 ollama 条目，ollama 模型若走 inferFeatures 会一律回落 generic
 * （所有功能位为 false），等于「什么都不支持」。所以 ollama 单开一条通道：
 * 优先用发现模型时落盘的实时信息（capabilities / ctx），离线时用内置知识表。 */

/** ollama 实时信息 → 归一结构（调用方从 model-meta 的 caps/info 组装） */
export function ollamaLive(info) {
  const i = info || {};
  return {
    ctx: Number(i.ctx) > 0 ? Number(i.ctx) : null,
    ctxMax: Number(i.ctxMax) > 0 ? Number(i.ctxMax) : null,
    numCtx: Number(i.numCtx) > 0 ? Number(i.numCtx) : null,
    capabilities: Array.isArray(i.capabilities) ? i.capabilities : (Array.isArray(i.caps) ? i.caps : []),
    parameterSize: i.parameterSize || '',
    quantization: i.quantization || '',
    family: i.family || '',
  };
}

/**
 * 统一能力解析：ollama 走本地记录，其余走内核能力档案。
 * 所有渲染点（设置页卡片 / 添加模型弹窗 / 属性面板）都用这个，避免三处各判一次。
 * @param {string} vendor 供应商键
 * @param {string} model 模型 id
 * @param {string} [baseUrl] 端点（非 ollama 的域名回落用）
 * @param {object} [live] ollama 实时信息（可选）
 */
export function resolveFeatures(vendor, model, baseUrl, live) {
  if (String(vendor == null ? '' : vendor).toLowerCase() === 'ollama') {
    return resolveOllamaModel(model, ollamaLive(live)).features;
  }
  return inferFeatures(vendor, model, baseUrl);
}

/** ollama 版本提示（非 ollama 返回 ''）。live 缺省时用内置知识表推断 */
export function ollamaHint(vendor, model, live) {
  if (String(vendor == null ? '' : vendor).toLowerCase() !== 'ollama') return '';
  return ollamaVersionHint(model, ollamaLive(live));
}

/* 功能标签定义；levels 由 thinkLevels 派生渲染，不单独出标签 */
export const FEAT_META = [
  { key: 'reasoning', label: '深度思考',   cls: 'f-reason' },
  { key: 'levels',    label: '多思考深度', cls: 'f-levels' },
  { key: 'tools',     label: '工具调用',   cls: 'f-tools' },
  { key: 'files',     label: '文件读取',   cls: 'f-files' },
  { key: 'vision',    label: '图片查看',   cls: 'f-vision' },
];

/**
 * 功能标签 pills HTML（tagCls 为标签类名前缀，如 'mm-tag' / 's-tag'）
 * 思考挡位单独渲染成一枚标签：档位少时列出来，多了折成「N 档」，完整清单进 tooltip。
 */
export function tagsHtml(features, tagCls) {
  const feats = features || {};
  const out = FEAT_META
    .filter(function (f) { return f.key !== 'levels' && feats[f.key]; })
    .map(function (f) { return '<span class="' + tagCls + ' ' + f.cls + '">' + f.label + '</span>'; });

  const lv = Array.isArray(feats.thinkLevels) ? feats.thinkLevels : [];
  if (lv.length) {
    const names = lv.map(function (k) { return THINK_LABEL[k] || k; }).join('/');
    const text = lv.length <= 3 ? ('思考 ' + names) : ('思考 ' + lv.length + ' 档');
    out.push('<span class="' + tagCls + ' f-levels" title="支持的思考挡位：' + names + '">' + text + '</span>');
  } else if (feats.levels) {
    // 兼容早期已存记录：只有 levels 布尔、没有 thinkLevels 数组
    out.push('<span class="' + tagCls + ' f-levels">多思考深度</span>');
  }
  return out.join('');
}
