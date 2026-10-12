/**
 * Ollama 模型信息记录（按模型）
 * ==============================
 * 内核档案（kernel-profiles.js）没有 ollama 条目，ollama 模型一律回落 generic
 * →「思考能力未知」。本模块补上这一层，**按模型**记录能力与版本形态。
 *
 * 两个数据来源，优先级从高到低：
 *   1. 实时：ollama `GET /api/tags` 的 details.context_length / capabilities
 *      （capabilities 里直接给 tools / thinking / vision / embedding，是权威值）
 *   2. 内置知识表：按模型家族名匹配的兜底（离线也能给个合理值）+ 版本形态识别
 *
 * 「版本形态」从模型名推断（去审查版 / 指令版 / 代码版 / 视觉版 / 推理版 / 嵌入版），
 * 用于在模型卡片上给一条 ollama 专属提示 —— 这正是社区模型最容易踩坑的地方
 * （同名同尺寸的 instruct 版与 uncensored 版能力、行为差很多）。
 */

/* ── 版本形态：按优先级匹配，取首条命中 ──
 * 顺序有讲究：去审查版往往同时带 instruct 字样（如 dolphin-llama3:8b-instruct），
 * 必须先判去审查，否则会被指令版吃掉。 */
const VARIANTS = [
  {
    key: 'uncensored', label: '去审查版',
    hint: '社区去审查 / 无对齐微调（Dolphin、abliterated、uncensored 等），内容约束更松',
    re: /(uncensored|abliterated|heretic|dolphin|wizard-vicuna|unaligned|nsfw|amoral)/i,
  },
  {
    key: 'embed', label: '嵌入版',
    hint: '向量嵌入模型，只做检索 / 召回，不参与对话',
    re: /(embed|bge[-_]?|gte[-_]?|e5[-_]|nomic-embed|mxbai-embed)/i,
  },
  {
    key: 'vision', label: '视觉版',
    hint: '多模态，可看图（llava / moondream / minicpm-v / *-vl / gemma3 等）',
    re: /(vision|llava|bakllava|moondream|minicpm-v|qwen[\w.-]*vl|gemma3)/i,
  },
  {
    key: 'reason', label: '推理版',
    hint: '长链推理模型（r1 / qwq / thinking），回答前会先思考',
    re: /(r1\b|qwq|reason|think|marco-o1)/i,
  },
  {
    key: 'coder', label: '代码版',
    hint: '代码专精微调（coder / starcoder / sqlcoder 等）',
    re: /(coder|codeqwen|codellama|starcoder|sqlcoder|deepseek-coder)/i,
  },
  {
    key: 'instruct', label: '指令版',
    hint: '指令微调版（instruct / -it / chat），按对话格式训练',
    re: /(instruct|[-_.]it\b|[-_.]it[-_.]|chat|turbo)/i,
  },
];

/** 内置家族知识表：离线兜底（有实时数据时以实时为准） */
const FAMILIES = [
  { re: /^llama3(\.\d+)?/,        name: 'Llama 3.x',   ctx: 131072, caps: ['completion', 'tools'] },
  { re: /^llama2/,                name: 'Llama 2',     ctx: 4096,   caps: ['completion'] },
  { re: /^qwen3/,                 name: 'Qwen 3',      ctx: 40960,  caps: ['completion', 'tools', 'thinking'] },
  { re: /^qwen2\.5/,              name: 'Qwen 2.5',    ctx: 32768,  caps: ['completion', 'tools'] },
  { re: /^qwen2(?!\.5)/,          name: 'Qwen 2',      ctx: 32768,  caps: ['completion'] },
  { re: /^deepseek-r1/,           name: 'DeepSeek-R1', ctx: 65536,  caps: ['completion', 'thinking'] },
  { re: /^deepseek/,              name: 'DeepSeek',    ctx: 65536,  caps: ['completion'] },
  { re: /^(mistral|mixtral)/,     name: 'Mistral',     ctx: 32768,  caps: ['completion', 'tools'] },
  { re: /^gemma3/,                name: 'Gemma 3',     ctx: 131072, caps: ['completion', 'vision'] },
  { re: /^gemma2?/,               name: 'Gemma',       ctx: 8192,   caps: ['completion'] },
  { re: /^phi4/,                  name: 'Phi-4',       ctx: 16384,  caps: ['completion'] },
  { re: /^phi3/,                  name: 'Phi-3',       ctx: 131072, caps: ['completion'] },
  { re: /^llava|^bakllava/,       name: 'LLaVA',       ctx: 4096,   caps: ['completion', 'vision'] },
  { re: /^codellama/,             name: 'Code Llama',  ctx: 16384,  caps: ['completion'] },
  { re: /^starcoder2?/,           name: 'StarCoder',   ctx: 16384,  caps: ['completion'] },
  { re: /^nomic-embed|^bge-|^mxbai-embed/, name: 'Embedding', ctx: 8192, caps: ['embedding'] },
];

/** 从模型名推断版本形态；识别不出返回「通用版」 */
export function detectVariant(model) {
  const id = String(model == null ? '' : model);
  for (let i = 0; i < VARIANTS.length; i++) {
    if (VARIANTS[i].re.test(id)) {
      return { key: VARIANTS[i].key, label: VARIANTS[i].label, hint: VARIANTS[i].hint };
    }
  }
  return { key: 'general', label: '通用版', hint: '未识别到特定微调形态，按基础对话模型处理' };
}

/** 命中内置家族知识表；未命中返回 null */
export function detectFamily(model) {
  const id = String(model == null ? '' : model).toLowerCase();
  for (let i = 0; i < FAMILIES.length; i++) {
    if (FAMILIES[i].re.test(id)) return FAMILIES[i];
  }
  return null;
}

/**
 * 把 ollama 的 capabilities 映射成前端功能位。
 * @param {string[]} caps ollama 返回的 capabilities（completion/tools/thinking/vision/embedding）
 */
export function featuresFromCaps(caps) {
  const has = (k) => Array.isArray(caps) && caps.indexOf(k) >= 0;
  const embed = has('embedding');
  return {
    reasoning: has('thinking'),
    levels: has('thinking'),
    thinkLevels: has('thinking') ? ['low', 'medium', 'high'] : [],
    tools: has('tools'),
    files: false,          // ollama 无文件上传/读取通道
    vision: has('vision'),
    nonChat: embed,
  };
}

/**
 * 解析一个 ollama 模型的能力与版本信息。
 * @param {string} model 模型名（如 qwen2.5:0.5b）
 * @param {{ctx?:number, capabilities?:string[], parameterSize?:string, quantization?:string, family?:string}} [live]
 *        来自 ollama /api/tags 的实时数据（可选）
 * @returns {{ctx:number|null, features:object, variant:object, family:object|null,
 *            parameterSize:string, quantization:string, source:'live'|'builtin'}}
 */
export function resolveOllamaModel(model, live) {
  const fam = detectFamily(model);
  const variant = detectVariant(model);
  const l = live || {};
  const liveCaps = Array.isArray(l.capabilities) ? l.capabilities : null;

  const caps = liveCaps && liveCaps.length ? liveCaps : (fam ? fam.caps : ['completion']);
  const features = featuresFromCaps(caps);
  // 名字里带 vision / uncensored 等特征时，补强（ollama 的 capabilities 有时不含 vision）
  if (variant.key === 'vision') features.vision = true;
  if (variant.key === 'embed') { features.nonChat = true; features.tools = false; }

  const ctx = Number(l.ctx) > 0 ? Number(l.ctx) : (fam && fam.ctx ? fam.ctx : null);
  // 架构上限（GGUF 声明）与用户设置的上限（Modelfile num_ctx）可能不同：
  // 生效的是 num_ctx；架构上限只作说明用。
  const ctxMax = Number(l.ctxMax) > 0 ? Number(l.ctxMax) : null;

  return {
    ctx: ctx,
    ctxMax: ctxMax,
    numCtx: Number(l.numCtx) > 0 ? Number(l.numCtx) : null,
    features: features,
    variant: variant,
    family: fam ? { name: fam.name } : null,
    parameterSize: l.parameterSize || '',
    quantization: l.quantization || '',
    source: (liveCaps && liveCaps.length) || Number(l.ctx) > 0 ? 'live' : 'builtin',
  };
}

/** 卡片上的 ollama 专属版本提示（一句话）。识别不出返回 '' */
export function versionHint(model, live) {
  const r = resolveOllamaModel(model, live);
  const bits = [];
  bits.push(r.variant.label);
  if (r.parameterSize) bits.push(r.parameterSize);
  if (r.quantization) bits.push(r.quantization);
  return bits.join(' · ');
}
