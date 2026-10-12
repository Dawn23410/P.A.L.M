/**
 * 模型附加属性（上下文长度 / 备注）
 * ==================================
 * 为什么单独存一份：内核的 ProviderConfig.models 是 List[str]，**没有任何按模型的
 * 元数据字段**，档案里也只有 max_output（最大输出 token）而没有「上下文长度」。
 * 所以前端单独存一份按 provider::model 索引的展示属性。
 *
 * 边界（避免又变成双轨）：
 *   - 内核配置拥有「有哪些模型」——增删模型一律写内核；
 *   - 本模块只拥有「这些模型的展示属性」——上下文长度、备注，不参与任何请求。
 * 内核哪天补了对应字段，这里应该整体迁回内核。
 */

const KEY = 'webui.model-meta';

/** 键：providerId + '::' + model（模型名可能含冒号，所以分隔符用双冒号） */
export function metaKey(providerId, model) {
  return String(providerId == null ? '' : providerId) + '::' + String(model == null ? '' : model);
}

function readAll() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY));
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  } catch (e) {
    return {};
  }
}

function writeAll(obj) {
  try { localStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) { /* 存储不可用：静默 */ }
}

/** 取一条（永不为 null，缺省字段用空值） */
export function getMeta(providerId, model) {
  const m = readAll()[metaKey(providerId, model)];
  return {
    ctx: m && m.ctx != null && m.ctx !== '' ? Number(m.ctx) : null,
    note: (m && m.note) || '',
    // ollama 专属：发现模型时一并落盘的实时信息（capabilities / 参数量 / 量化 / 家族）
    caps: m && Array.isArray(m.caps) ? m.caps.slice() : [],
    info: m && m.info && typeof m.info === 'object' ? { ...m.info } : {},
  };
}

/** 合并写入；ctx 传 null/'' 表示清空 */
export function setMeta(providerId, model, patch) {
  const all = readAll();
  const k = metaKey(providerId, model);
  const cur = all[k] || {};
  const next = { ...cur };
  if ('ctx' in patch) {
    const v = patch.ctx;
    if (v === null || v === undefined || v === '') delete next.ctx;
    else {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) next.ctx = Math.floor(n);
      else delete next.ctx;
    }
  }
  if ('note' in patch) {
    const s = String(patch.note == null ? '' : patch.note).trim();
    if (s) next.note = s; else delete next.note;
  }
  if ('caps' in patch) {
    const arr = Array.isArray(patch.caps) ? patch.caps.filter((x) => typeof x === 'string' && x) : [];
    if (arr.length) next.caps = arr; else delete next.caps;
  }
  if ('info' in patch) {
    const src = patch.info && typeof patch.info === 'object' ? patch.info : {};
    const obj = {};
    for (const k of ['family', 'parameterSize', 'quantization']) {
      const v = String(src[k] == null ? '' : src[k]).trim();
      if (v) obj[k] = v;
    }
    // 架构上限（GGUF 声明的 context_length），与生效的 num_ctx 可能不同，留作说明
    const cm = Number(src.ctxMax);
    if (Number.isFinite(cm) && cm > 0) obj.ctxMax = Math.floor(cm);
    if (Object.keys(obj).length) next.info = obj; else delete next.info;
  }
  if (Object.keys(next).length) all[k] = next; else delete all[k];
  writeAll(all);
  return getMeta(providerId, model);
}

export function removeMeta(providerId, model) {
  const all = readAll();
  delete all[metaKey(providerId, model)];
  writeAll(all);
}

/** 模型改名时把属性挪到新键，避免属性丢失 */
export function renameMeta(providerId, oldModel, newModel) {
  if (oldModel === newModel) return;
  const all = readAll();
  const from = metaKey(providerId, oldModel);
  const to = metaKey(providerId, newModel);
  if (all[from]) {
    all[to] = all[from];
    delete all[from];
    writeAll(all);
  }
}

/** 只保留给定键，清掉已删除模型的残留属性 */
export function pruneMeta(validKeys) {
  const all = readAll();
  const keep = {};
  let dropped = 0;
  for (const k in all) {
    if (Object.prototype.hasOwnProperty.call(all, k) && validKeys[k]) keep[k] = all[k];
    else dropped++;
  }
  if (dropped) writeAll(keep);
  return dropped;
}

/** 把 token 数渲染成人类可读（131072 -> 128K） */
export function formatCtx(n) {
  if (!n || !Number.isFinite(Number(n))) return '';
  const v = Number(n);
  if (v < 1000) return String(v);
  // 上下文长度两种写法都常见，且都该显示成"整数 K"：
  //   131072（=128×1024）惯例叫 128K
  //   128000（=128×1000）也叫 128K
  // 但 128000 恰好也能被 1024 整除（=125），所以判断顺序必须是
  // "先看 1000 整除、再看 1024 整除"，否则 128000 会显示成 125K。
  let k;
  if (v % 1000 === 0) k = v / 1000;
  else if (v % 1024 === 0) k = v / 1024;
  else k = v / 1000;
  // 超过 1024K 改说 M：1048576 显示 1M 而不是 1024K（同上，先看 1048576 再看 1e6）
  if (k >= 1024) {
    let m;
    if (v % 1048576 === 0) m = v / 1048576;
    else if (v % 1000000 === 0) m = v / 1000000;
    else m = k / 1024;
    const mShown = Math.abs(m - Math.round(m)) < 0.05 ? Math.round(m) : Number(m.toFixed(1));
    return mShown + 'M';
  }
  const shown = Math.abs(k - Math.round(k)) < 0.05 ? Math.round(k) : Number(k.toFixed(1));
  return shown + 'K';
}
