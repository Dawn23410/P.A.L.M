/**
 * 设置→聊天→「模型设置」分区
 * ========================
 * 数据源：**内核配置** GET/POST /api/config（唯一事实来源）。
 * 早期版本把模型存在 localStorage['webui.models']，与内核 config.json 形成双轨 ——
 * 在 UI 里加模型对内核毫无影响，而内核只认 config.json 的 active_provider/active_model。
 * 现已统一：本模块读写内核配置，历史 localStorage 数据在上线时一次性迁移。
 *
 * 能力标签按内核能力档案实时推断（vendor-data.js → kernel-profiles.js），前端不存。
 * 「上下文长度 / 备注」内核 schema 没有，存在 model-meta.js（详见该文件注释）。
 *
 * 卡片上**不再有整卡点击生效**：改生效、改属性、删除都走显式按钮，
 * 避免"点哪儿都能触发"的误操作。
 */

import { openModelModal } from './model-modal.js';
import { openModelProps } from './model-props.js';
import { confirmDialog } from './ui-confirm.js';
import { tagsHtml, resolveFeatures, ollamaHint, VENDORS, PROTOCOLS } from './vendor-data.js';
import {
  getConfig, saveConfig, normalizeConfig, findProvider, flattenModels, KEY_MASK,
} from './kernel-api.js';
import { getMeta, setMeta, removeMeta, renameMeta, formatCtx, metaKey } from './model-meta.js';

const STYLE_ID = 'mod-models-style';
const LEGACY_KEY = 'webui.models';           // 旧的 localStorage 键
const MIGRATED_KEY = 'webui.models.migrated';
const BACKUP_KEY = 'webui.models.backup';    // 迁移后的脱敏备份（剥掉 api_key）

const CSS = `
.mod-settings .s-model-list{
  /* 容器加长：原来固定 220px，模型一多就要一直滚。改成随视口伸缩 */
  max-height:min(52vh, 520px);
  min-height:120px;
  overflow-y:auto;
  border:1px solid var(--ui-border-soft,#ececec);border-radius:10px;
  background:var(--ui-elev,#fff);
  scrollbar-width:thin;
}
.mod-settings .s-model-list::-webkit-scrollbar{ width:8px; }
.mod-settings .s-model-list::-webkit-scrollbar-thumb{
  background:var(--ui-border,#e4e6ea);border-radius:4px;
}
.mod-settings .s-model-list::-webkit-scrollbar-thumb:hover{ background:var(--ui-faint,#9a9a9a); }
.mod-settings .s-model-list::-webkit-scrollbar-track{ background:transparent; }

.mod-settings .s-model-empty{
  padding:24px;text-align:center;
  font-size:0.8571rem;color:var(--ui-faint,#9a9a9a);
}
.mod-settings .s-mcard{
  display:flex;align-items:center;gap:10px;
  padding:10px 12px;border-bottom:1px solid var(--ui-border-soft,#ececec);
  position:relative;
}
.mod-settings .s-mcard:last-child{border-bottom:none;}
/* 当前生效项（内核 active_provider/active_model） */
.mod-settings .s-mcard.on::before{
  content:"";position:absolute;left:0;top:50%;transform:translateY(-50%);
  width:3px;height:26px;border-radius:0 3px 3px 0;background:var(--ui-accent);
}
.mod-settings .s-mcard .n{
  font-weight:600;font-size:0.9286rem;word-break:break-all;
}
.mod-settings .s-mcard .m{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);
  display:flex;flex-wrap:wrap;gap:4px 14px;
}
.mod-settings .s-mcard .m .kv{ display:inline-flex;align-items:center;gap:5px; }
.mod-settings .s-mcard .m .kv i{
  font-style:normal;color:var(--ui-faint,#9a9a9a);opacity:.7;
}
.mod-settings .s-mcard .m .kv i::after{ content:""; }
.mod-settings .s-cap{
  font-size:0.7143rem;color:var(--ui-faint,#9a9a9a);
  align-self:center;margin-right:2px;
}
.mod-settings .s-mcard .info{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px;}
.mod-settings .s-mcard .acts{flex:none;display:flex;align-items:center;gap:6px;}
.mod-settings .s-mcard .act{
  height:26px;padding:0 10px;border-radius:7px;cursor:pointer;
  border:1px solid var(--ui-border,#e4e6ea);background:var(--ui-elev,#fff);
  font-family:inherit;font-size:0.7857rem;color:var(--ui-text,#1a1a1a);
  transition:background .16s,color .16s,border-color .16s;
  white-space:nowrap;
}
.mod-settings .s-mcard .act:hover{ background:var(--ui-hover); }
.mod-settings .s-mcard .act.del{
  width:26px;padding:0;color:var(--ui-faint,#9a9a9a);font-size:0.9286rem;line-height:1;
}
.mod-settings .s-mcard .act.del:hover{ color:var(--ui-danger,#d1242f); }

/* 功能标签：多色 pill（与 model-modal / model-props 同色系） */
.mod-settings .s-mcard .tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;}
.mod-settings .s-mcard .tags:empty{display:none;}
.mod-settings .s-tag{
  display:inline-block;padding:0 7px;border-radius:999px;
  font-size:0.7143rem;line-height:1.6;white-space:nowrap;
}
.mod-settings .s-tag.f-reason{background:#f3e8ff;color:#8250df;}
.mod-settings .s-tag.f-levels{background:#dff5f2;color:#0f7f72;}
.mod-settings .s-tag.f-tools{background:#e3effc;color:#0969da;}
.mod-settings .s-tag.f-files{background:#ffeed9;color:#b45e04;}
.mod-settings .s-tag.f-vision{background:#ffe3ec;color:#c22758;}
.mod-settings .s-tag.f-ctx{background:#eef0f3;color:#5b6572;}
/* ollama 专属版本提示（去审查版 / 指令版 / 视觉版 …） */
.mod-settings .s-tag.f-ver{background:#eaf7ee;color:#1a7f37;border:1px solid #bfe6cc;}

/* 内核不可达时的兜底：不能让设置页整个崩掉 */
.mod-settings .s-model-err{
  padding:16px;border:1px solid var(--ui-danger,#d1242f);border-radius:10px;
  background:var(--ui-elev,#fff);
}
.mod-settings .s-model-err .h{
  display:flex;align-items:center;gap:8px;
  font-size:0.9286rem;font-weight:600;color:var(--ui-danger,#d1242f);margin-bottom:6px;
}
.mod-settings .s-model-err .body{
  font-size:0.8571rem;color:var(--ui-muted,#6b6b6b);line-height:1.6;margin-bottom:10px;
  word-break:break-word;
}
.mod-settings .s-model-err .hint{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);line-height:1.6;
  background:var(--ui-hover);border-radius:6px;padding:8px 10px;margin-bottom:10px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
.mod-settings .s-model-retry{
  height:30px;padding:0 14px;border:1px solid var(--ui-border);border-radius:8px;
  background:var(--ui-elev);font-family:inherit;font-size:0.8571rem;
  color:var(--ui-text);cursor:pointer;transition:background .16s;
}
.mod-settings .s-model-retry:hover{ background:var(--ui-hover); }
.mod-settings .s-model-note{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);
  margin:8px 0 0;line-height:1.6;
}
`;

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

const typeLabel = (t) => {
  const p = PROTOCOLS.filter((x) => x.key === t)[0];
  return p ? p.label : (t || '');
};

/** 模型名/供应商名来自内核配置（源头是上游 discover），拼 HTML 前必须转义 */
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

/**
 * 一次性迁移：把 localStorage['webui.models'] 并进内核配置。
 * - 只补不覆盖：provider 已存在的模型不重复加
 * - 迁移 key：旧结构里存了明文 api_key，若目标 provider 还没 key 就补上
 * - 迁移完把 blob 脱敏后挪到备份键并删掉原键（明文 key 不该长留 localStorage）
 * @returns {{config: object, added: number, migrated: boolean}}
 */
function migrateLegacy(cfg) {
  let legacy = null;
  try { legacy = JSON.parse(localStorage.getItem(LEGACY_KEY)); } catch (e) { legacy = null; }
  if (!Array.isArray(legacy) || !legacy.length) return { config: cfg, added: 0, migrated: false };

  let added = 0;
  const backup = [];
  for (let i = 0; i < legacy.length; i++) {
    const e = legacy[i];
    if (!e || !e.vendor || !e.model) continue;
    let p = findProvider(cfg, e.vendor);
    if (!p) {
      const v = VENDORS[e.vendor] || {};
      p = {
        id: e.vendor,
        name: v.label || e.vendor,
        type: e.type || v.type || 'openai_compat',
        base_url: e.base || v.base || '',
        api_key: '',
        models: [],
      };
      cfg.providers.push(p);
    }
    if (!Array.isArray(p.models)) p.models = [];
    if (p.models.indexOf(e.model) < 0) { p.models.push(e.model); added++; }
    if (e.key && e.key !== KEY_MASK && !p.api_key) p.api_key = e.key;
    // 备份里剥掉 key
    backup.push({ vendor: e.vendor, model: e.model, type: e.type, base: e.base });
  }
  try {
    localStorage.setItem(BACKUP_KEY, JSON.stringify(backup));
    localStorage.removeItem(LEGACY_KEY);
    localStorage.setItem(MIGRATED_KEY, '1');
  } catch (err) { /* 存储不可用就跳过，不阻塞主流程 */ }
  return { config: cfg, added: added, migrated: true };
}
/**
 * 挂载模型设置分区（容器由 settings.js 提供）。
 * @returns {{ destroy: () => void }}
 */
export function mountModelSection(container) {
  injectStyle();
  container.innerHTML = `
    <div class="s-model-head">
      <div class="s-label">模型设置</div>
      <button class="s-model-add" type="button" data-add>添加模型</button>
    </div>
    <div class="s-model-list" data-list></div>
    <div data-note></div>`;

  const listBox = container.querySelector('[data-list]');
  const noteBox = container.querySelector('[data-note]');
  const addBtn = container.querySelector('[data-add]');

  let cfg = null;        // 当前内核配置（内存镜像，写成功后才更新）
  let busy = false;
  let alive = true;

  const setBtnIdle = () => {
    if (!alive) return;
    addBtn.disabled = !cfg;
    // 只在文案真的不同时才写：直接赋值 textContent 会替换文本节点，
    // 即使内容一样也会产生一次 DOM 变更，肉眼看着像"闪了一下"。
    if (addBtn.textContent !== '添加模型') addBtn.textContent = '添加模型';
  };

  const setNote = (text) => {
    noteBox.innerHTML = text ? '<p class="s-model-note">' + esc(text) + '</p>' : '';
  };

  const renderError = (msg) => {
    listBox.innerHTML = `
      <div class="s-model-err">
        <div class="h"><span>●</span><span>读不到内核配置</span></div>
        <div class="body">${esc(msg)}</div>
        <div class="hint">python -m palm_llm.server.api</div>
        <button class="s-model-retry" type="button" data-retry>重试</button>
      </div>`;
    addBtn.disabled = true;
    addBtn.textContent = '添加模型';
  };

  const render = () => {
    if (!cfg) return;
    const rows = flattenModels(cfg);
    if (!rows.length) {
      listBox.innerHTML = '<div class="s-model-empty">暂无模型，点右上角「添加模型」</div>';
      return;
    }
    listBox.innerHTML = rows.map((r) => {
      // 上下文长度 / ollama 记录都是前端附加属性（内核没有这些字段）
      const m = getMeta(r.providerId, r.model);
      // 能力标签：ollama 取「模型信息记录」，其余由内核档案实时推断，均不存库
      const live = {
        ctx: m.ctx, capabilities: m.caps,
        ctxMax: m.info.ctxMax,
        parameterSize: m.info.parameterSize,
        quantization: m.info.quantization,
        family: m.info.family,
      };
      const feats = resolveFeatures(r.providerId, r.model, r.baseUrl, live);
      // 上下文长度始终占位显示：未填写时也要让人一眼看出"这个字段是空的"，
      // 而不是干脆不出现（那样就分不清"没填"和"不支持"）。
      const ctxText = m.ctx ? formatCtx(m.ctx) : '未填写';
      // ollama：生效上限（num_ctx）与架构上限不同时，用 tooltip 说明
      const ctxMax = Number(m.info.ctxMax) > 0 ? Number(m.info.ctxMax) : 0;
      const ctxTitle = (ctxMax && m.ctx && ctxMax > m.ctx)
        ? ' title="已设上下文 ' + esc(formatCtx(m.ctx)) + '，模型架构上限 ' + esc(formatCtx(ctxMax)) + '"'
        : '';
      const noteTag = m.note ? '<span class="s-tag f-ctx" title="' + esc(m.note) + '">备注</span>' : '';
      // ollama 专属版本提示（去审查版 / 指令版 / 视觉版 …）
      const ver = ollamaHint(r.providerId, r.model, live);
      const verTag = ver
        ? '<span class="s-tag f-ver" title="ollama 模型版本形态">' + esc(ver) + '</span>'
        : '';
      return `
      <div class="s-mcard${r.active ? ' on' : ''}" data-pid="${esc(r.providerId)}" data-model="${esc(r.model)}">
        <div class="info">
          <span class="n">${esc(r.model)}</span>
          <span class="m">
            <span class="kv"><i>供应商</i>${esc(r.providerName)}</span>
            <span class="kv"><i>协议</i>${esc(typeLabel(r.providerType))}</span>
            <span class="kv"${ctxTitle}><i>上下文</i>${esc(ctxText)}</span>
          </span>
          <div class="tags"><span class="s-cap">支持</span>${verTag}${tagsHtml(feats, 's-tag')}${noteTag}</div>
        </div>
        <div class="acts">
          <button class="act" type="button" data-props>属性</button>
          <button class="act del" type="button" data-del aria-label="删除模型">×</button>
        </div>
      </div>`;
    }).join('');
  };

  /**
   * 写内核配置；成功才更新内存镜像并重渲染。
   * @param {object} next 新配置
   * @param {string} [busyLabel] 只有需要显示进度的操作（添加）才传，
   *   否则按钮文案一动，切换/删除这种瞬时操作就会闪一下又变回来。
   */
  const persist = async (next, busyLabel) => {
    if (busy) return false;
    busy = true;
    addBtn.disabled = true;
    if (busyLabel) addBtn.textContent = busyLabel;
    try {
      await saveConfig(next);
      cfg = next;
      render();
      return true;
    } catch (e) {
      renderError(e && e.message ? e.message : String(e));
      return false;
    } finally {
      busy = false;
      setBtnIdle();
    }
  };

  const load = async () => {
    if (!alive) return;
    busy = true;
    addBtn.disabled = true;
    listBox.innerHTML = '<div class="s-model-empty">正在读取内核配置…</div>';
    setNote('');
    try {
      const raw = await getConfig();
      const c = normalizeConfig(raw);

      // 一次性迁移旧 localStorage 数据（双轨收敛的关键一步）
      const mig = migrateLegacy(c);
      if (mig.migrated) {
        if (mig.added > 0) {
          await saveConfig(c);
          setNote('已把 ' + mig.added + ' 个历史模型从浏览器本地存储迁移进内核配置（脱敏备份保留在 ' + BACKUP_KEY + '）。');
        } else {
          setNote('浏览器本地存储里没有需要迁移的新模型。');
        }
      }

      cfg = c;
      render();
    } catch (e) {
      cfg = null;
      renderError(e && e.message ? e.message : String(e));
    } finally {
      busy = false;
      setBtnIdle();
    }
  };

  /** 添加模型：并进对应 provider 的 models[]，必要时新建 provider */
  const onAdd = async (m) => {
    if (!cfg) return;
    const next = normalizeConfig(cfg);
    let p = findProvider(next, m.vendor);
    if (!p) {
      const v = VENDORS[m.vendor] || {};
      p = {
        id: m.vendor,
        name: v.label || m.vendor,
        type: m.type || v.type || 'openai_compat',
        base_url: m.base || v.base || '',
        api_key: '',
        models: [],
      };
      next.providers.push(p);
    }
    if (!Array.isArray(p.models)) p.models = [];
    if (p.models.indexOf(m.model) < 0) p.models.push(m.model);
    // key 只在用户确实填了新的才覆盖；遮罩值原样回传交给内核回填
    if (m.key && m.key !== KEY_MASK) p.api_key = m.key;
    if (m.base) p.base_url = m.base;
    if (m.type) p.type = m.type;
    // 弹窗里选的「上下文长度」写进前端附加属性（内核 schema 没有该字段）
    if (m.ctx) setMeta(m.vendor, m.model, { ctx: m.ctx });
    // 还没有生效模型时，第一个加进来的自动生效
    if (!next.active_model) {
      next.active_provider = p.id;
      next.active_model = m.model;
    }
    await persist(next, '处理中…');
  };

  /* 注：不再提供「设为当前」入口。内核按 config.json 的
     active_provider / active_model 发请求，这两个字段现在只能改配置文件。 */

  /** 属性面板：可改模型 ID（= 重命名内核条目）、上下文长度、备注 */
  const onProps = async (pid, model) => {
    const cur = normalizeConfig(cfg);
    const p = findProvider(cur, pid);
    if (!p) return;
    const panel = openModelProps({
      providerId: pid,
      model: model,
      providerName: p.name || pid,
      providerType: p.type,
      baseUrl: p.base_url,
      otherModels: (p.models || []).filter((x) => x !== model),
    });
    const res = await panel.result;
    if (!res || !alive) return;

    const renamed = res.model !== model;
    if (renamed) {
      const idx = (p.models || []).indexOf(model);
      if (idx < 0) return;
      p.models[idx] = res.model;
      renameMeta(pid, model, res.model);
      if (cur.active_provider === pid && cur.active_model === model) {
        cur.active_model = res.model;
      }
    }
    setMeta(pid, res.model, { ctx: res.ctx, note: res.note });

    if (renamed) await persist(cur);
    else render();          // 只改了附加属性：不必回写内核配置
  };

  /** 删除模型：先弹确认（会直接改写内核配置，不可撤销） */
  const onDelete = async (pid, model) => {
    const cur = normalizeConfig(cfg);
    const p = findProvider(cur, pid);
    if (!p) return;
    const ok = await confirmDialog({
      title: '删除模型',
      messageHtml: '确定从「<b>' + esc(p.name || pid) + '</b>」中删除 <b>' + esc(model) + '</b> 吗？'
        + '<br><br>这会直接改写内核配置（config.json），删除后需要重新添加。',
      okText: '删除',
      danger: true,
    });
    if (!ok || !alive) return;

    const next = normalizeConfig(cfg);
    const t = findProvider(next, pid);
    if (!t) return;
    t.models = (t.models || []).filter((x) => x !== model);
    if (next.active_provider === pid && next.active_model === model) {
      next.active_provider = '';
      next.active_model = '';
    }
    removeMeta(pid, model);
    await persist(next);
  };

  const onListClick = async (e) => {
    const card = e.target.closest('.s-mcard');
    if (!card) return;
    const pid = card.dataset.pid;
    const model = card.dataset.model;
    // 只认按钮，整卡不再可点（避免误触发）
    if (e.target.closest('[data-del]')) return onDelete(pid, model);
    if (e.target.closest('[data-props]')) return onProps(pid, model);
  };

  const onAddClick = () => {
    if (!cfg) return;
    openModelModal({
      onAdd: onAdd,
      // 「已添加」按当前内核配置判定，而不是再读一份前端存储
      isAdded: (vendorId, model) => {
        const p = findProvider(cfg, vendorId);
        return !!p && (p.models || []).indexOf(model) >= 0;
      },
    });
  };

  const onRetry = (e) => {
    if (e.target.closest('[data-retry]')) load();
  };

  addBtn.addEventListener('click', onAddClick);
  container.addEventListener('click', onListClick);
  listBox.addEventListener('click', onRetry);

  load();

  return {
    destroy() {
      alive = false;
      addBtn.removeEventListener('click', onAddClick);
      container.removeEventListener('click', onListClick);
      listBox.removeEventListener('click', onRetry);
      container.innerHTML = '';
    },
  };
}

