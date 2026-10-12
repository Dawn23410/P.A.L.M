/**
 * 模型属性面板
 * ============
 * 从「模型设置」卡片上的「属性」按钮打开。可改：模型 ID（= 重命名内核配置里的条目）、
 * 上下文长度、备注。其余（供应商 / 协议 / 端点 / 能力标签 / 思考挡位）为只读展示，
 * 因为那些要么来自内核配置、要么来自内核能力档案，前端不该在这里改。
 *
 * 上下文长度存在 model-meta.js：内核 schema 里没有这个字段（详见该文件注释）。
 */

import { resolveFeatures, ollamaHint, tagsHtml, PROTOCOLS, THINK_LEVELS } from './vendor-data.js';
import { getMeta, formatCtx } from './model-meta.js';

const STYLE_ID = 'model-props-style';

const CSS = `
.mp-mask{
  position:fixed;inset:0;z-index:1100;
  background:rgba(0,0,0,.42);
  display:flex;align-items:flex-start;justify-content:center;
  overflow:auto;padding:24px 16px;
}
.mp-panel{
  width:min(540px,100%);
  background:var(--ui-elev,#fff);
  color:var(--ui-text,#1a1a1a);
  border:1px solid var(--ui-border,#e0e0e0);
  border-radius:var(--ui-radius-lg,14px);
  box-shadow:var(--ui-shadow-2,0 16px 40px -12px rgba(0,0,0,.35));
  padding:20px;
  display:flex;flex-direction:column;gap:14px;
}
.mp-head{
  display:flex;align-items:center;justify-content:space-between;gap:12px;
}
.mp-head .t{font-size:1.0714rem;font-weight:600;}
.mp-head .x{
  flex:none;width:28px;height:28px;border:none;border-radius:8px;cursor:pointer;
  background:transparent;color:var(--ui-faint,#9a9a9a);font-size:1.0714rem;line-height:1;
  transition:background .16s,color .16s;
}
.mp-head .x:hover{background:var(--ui-hover);color:var(--ui-text);}

.mp-row{display:flex;align-items:center;gap:12px;}
.mp-row > label{
  flex:none;width:88px;text-align:right;
  font-size:0.8571rem;color:var(--ui-muted,#6b6b6b);
}
.mp-row input[type=text],.mp-row input[type=number]{
  flex:1 1 auto;min-width:0;height:34px;
  padding:0 10px;border-radius:8px;
  border:1px solid var(--ui-border,#e0e0e0);
  background:var(--ui-bg,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;outline:none;
  transition:border-color .16s,box-shadow .16s;
}
.mp-row input:focus{
  border-color:var(--ui-accent,#0969da);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--ui-accent,#0969da) 15%,transparent);
}
.mp-row input:disabled{opacity:.6;cursor:not-allowed;}
.mp-row .unit{flex:none;font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);min-width:64px;}
.mp-hint{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);line-height:1.6;
  margin-left:100px;
}
.mp-sec{
  border-top:1px solid var(--ui-border-soft,#ececec);padding-top:12px;
  display:flex;flex-direction:column;gap:10px;
}
.mp-sec .h{font-size:0.8571rem;font-weight:600;color:var(--ui-muted,#6b6b6b);letter-spacing:.4px;}
.mp-ro{display:flex;align-items:center;gap:12px;}
.mp-ro > span{
  flex:none;width:88px;text-align:right;
  font-size:0.8571rem;color:var(--ui-muted,#6b6b6b);
}
.mp-ro > .v{
  flex:1 1 auto;min-width:0;font-size:0.8571rem;color:var(--ui-text,#1a1a1a);
  word-break:break-all;
}
.mp-tags{display:flex;flex-wrap:wrap;gap:4px;flex:1 1 auto;}
.mp-foot{display:flex;justify-content:flex-end;gap:8px;border-top:1px solid var(--ui-border-soft,#ececec);padding-top:14px;}
.mp-btn{
  height:32px;padding:0 16px;border-radius:8px;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;transition:background .16s,opacity .16s;
}
.mp-btn:hover{background:var(--ui-hover);}
.mp-btn.mp-ok{
  border-color:transparent;
  background:var(--ui-accent-solid,#0969da);color:var(--ui-on-accent,#fff);
}
.mp-btn.mp-ok:hover{opacity:.88;background:var(--ui-accent-solid,#0969da);}
.mp-btn:disabled{opacity:.5;cursor:not-allowed;}
.mp-err{font-size:0.8571rem;color:var(--ui-danger,#d1242f);min-height:0;}
.mp-err:empty{display:none;}

/* 标签配色与 model-modal / models 保持一致 */
.mp-tag{
  display:inline-block;padding:0 7px;border-radius:999px;
  font-size:0.7143rem;line-height:1.7;white-space:nowrap;
}
.mp-tag.f-reason{background:#f3e8ff;color:#8250df;}
.mp-tag.f-levels{background:#dff5f2;color:#0f7f72;}
.mp-tag.f-tools{background:#e3effc;color:#0969da;}
.mp-tag.f-files{background:#ffeed9;color:#b45e04;}
.mp-tag.f-vision{background:#ffe3ec;color:#c22758;}
`;

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const protoLabel = (t) => {
  const p = PROTOCOLS.filter((x) => x.key === t)[0];
  return p ? p.label : (t || '');
};

/**
 * 打开模型属性面板。
 * @param {{
 *   providerId: string, model: string, providerName: string,
 *   providerType: string, baseUrl: string, otherModels: string[],
 * }} opts
 * @returns {{ close: () => void, result: Promise<{model:string,ctx:number|null,note:string}|null> }}
 */
export function openModelProps(opts) {
  injectStyle();
  const o = opts || {};
  const meta = getMeta(o.providerId, o.model);
  // 能力：ollama 走本地模型信息记录，其余走内核档案（与设置页/弹窗同一口径）
  const live = {
    ctx: meta.ctx, capabilities: meta.caps,
    ctxMax: meta.info.ctxMax,
    parameterSize: meta.info.parameterSize,
    quantization: meta.info.quantization,
    family: meta.info.family,
  };
  const feats = resolveFeatures(o.providerId, o.model, o.baseUrl, live);
  const ver = ollamaHint(o.providerId, o.model, live);
  const tiers = (feats.thinkLevels || [])
    .map((k) => {
      const t = THINK_LEVELS.filter((x) => x.key === k)[0];
      return t ? t.label : k;
    }).join(' / ') || '—';
  // 生效上限（ollama num_ctx）与架构上限不同时，一并标出
  const ctxMax = Number(meta.info.ctxMax) > 0 ? Number(meta.info.ctxMax) : 0;
  const ctxNote = (ctxMax && meta.ctx && ctxMax > meta.ctx)
    ? (formatCtx(meta.ctx) + ' / 架构上限 ' + formatCtx(ctxMax))
    : (meta.ctx ? formatCtx(meta.ctx) + ' tokens' : '未填写');

  let resolveResult = null;
  const result = new Promise((r) => { resolveResult = r; });

  const mask = document.createElement('div');
  mask.className = 'mp-mask';
  mask.innerHTML = `
    <div class="mp-panel" role="dialog" aria-modal="true">
      <div class="mp-head">
        <div class="t">模型属性</div>
        <button class="x" type="button" data-x aria-label="关闭">×</button>
      </div>

      <div class="mp-row">
        <label for="mp-model">模型 ID</label>
        <input id="mp-model" type="text" data-model value="${esc(o.model)}" />
      </div>
      <div class="mp-hint">改写模型 ID 会同步改名内核配置里的条目（同名视为重复，会被拒绝）。</div>

      <div class="mp-row">
        <label for="mp-ctx">上下文长度</label>
        <input id="mp-ctx" type="number" min="1" step="1000" data-ctx
               value="${meta.ctx == null ? '' : esc(String(meta.ctx))}"
               placeholder="如 128000" />
        <span class="unit" data-ctxhint>${ctxNote}</span>
      </div>
      <div class="mp-hint">内核配置里没有该字段（档案只有 max_output = 最大输出），所以由前端单独记录，仅用于展示。</div>

      <div class="mp-row">
        <label for="mp-note">备注</label>
        <input id="mp-note" type="text" data-note value="${esc(meta.note)}" placeholder="选填" />
      </div>

      <div class="mp-sec">
        <div class="h">来自内核配置（只读）</div>
        <div class="mp-ro"><span>供应商</span><div class="v">${esc(o.providerName || o.providerId)}　<span style="opacity:.6">${esc(o.providerId)}</span></div></div>
        <div class="mp-ro"><span>协议</span><div class="v">${esc(protoLabel(o.providerType))}</div></div>
        <div class="mp-ro"><span>端点</span><div class="v">${esc(o.baseUrl || '—')}</div></div>
      </div>

      <div class="mp-sec">
        <div class="h">能力与版本（只读推断）</div>
        <div class="mp-ro"><span>能力</span><div class="mp-tags">${tagsHtml(feats, 'mp-tag') || '<span style="color:var(--ui-faint)">无</span>'}</div></div>
        ${ver ? `<div class="mp-ro"><span>版本形态</span><div class="v">${esc(ver)}</div></div>` : ''}
        <div class="mp-ro"><span>思考挡位</span><div class="v">${esc(tiers)}</div></div>
      </div>

      <div class="mp-err" data-err></div>
      <div class="mp-foot">
        <button class="mp-btn" type="button" data-cancel>取消</button>
        <button class="mp-btn mp-ok" type="button" data-save>保存</button>
      </div>
    </div>`;

  const panel = mask.querySelector('.mp-panel');
  const modelInp = mask.querySelector('[data-model]');
  const ctxInp = mask.querySelector('[data-ctx]');
  const noteInp = mask.querySelector('[data-note]');
  const ctxHint = mask.querySelector('[data-ctxhint]');
  const errBox = mask.querySelector('[data-err]');

  let closed = false;
  const close = (val) => {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey, true);
    mask.remove();
    resolveResult(val === undefined ? null : val);
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(null); }
  };

  ctxInp.addEventListener('input', () => {
    const n = Number(ctxInp.value);
    ctxHint.textContent = (ctxInp.value && Number.isFinite(n) && n > 0) ? (formatCtx(n) + ' tokens') : '未填写';
  });

  mask.querySelector('[data-x]').addEventListener('click', () => close(null));
  mask.querySelector('[data-cancel]').addEventListener('click', () => close(null));
  mask.addEventListener('mousedown', (e) => { if (!panel.contains(e.target)) close(null); });

  mask.querySelector('[data-save]').addEventListener('click', () => {
    const newModel = modelInp.value.trim();
    errBox.textContent = '';
    if (!newModel) { errBox.textContent = '模型 ID 不能为空。'; return; }
    if (newModel !== o.model) {
      const dup = (o.otherModels || []).indexOf(newModel) >= 0;
      if (dup) { errBox.textContent = '该供应商下已经有同名模型了。'; return; }
    }
    const rawCtx = ctxInp.value.trim();
    let ctx = null;
    if (rawCtx) {
      const n = Number(rawCtx);
      if (!Number.isFinite(n) || n <= 0) { errBox.textContent = '上下文长度要填正整数。'; return; }
      ctx = Math.floor(n);
    }
    close({ model: newModel, ctx: ctx, note: noteInp.value.trim() });
  });

  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(mask);
  modelInp.focus();

  return { close: () => close(null), result: result };
}
