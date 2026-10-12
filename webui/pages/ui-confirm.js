/**
 * 通用确认弹窗
 * ==============
 * 用自绘弹窗而不是 window.confirm：后者会阻塞渲染、样式不可控、
 * 且在本项目的暗色主题下是刺眼的白框。这里与 model-modal 同一套蒙版/面板风格。
 *
 * 用法：
 *   const ok = await confirmDialog({ title: '删除模型', message: '...', danger: true });
 */

const STYLE_ID = 'ui-confirm-style';

const CSS = `
.uc-mask{
  position:fixed;inset:0;z-index:1200;
  background:rgba(0,0,0,.42);
  display:flex;align-items:center;justify-content:center;
  padding:16px;
}
.uc-panel{
  width:min(400px,100%);
  background:var(--ui-elev,#fff);
  color:var(--ui-text,#1a1a1a);
  border:1px solid var(--ui-border,#e0e0e0);
  border-radius:var(--ui-radius-lg,14px);
  box-shadow:var(--ui-shadow-2,0 12px 32px -10px rgba(0,0,0,.3));
  padding:20px;
  display:flex;flex-direction:column;gap:12px;
  animation:ucIn .16s var(--ui-ease,cubic-bezier(.2,.7,.3,1));
}
@keyframes ucIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.uc-title{font-size:1rem;font-weight:600;line-height:1.4;}
.uc-msg{
  font-size:0.9286rem;line-height:1.7;color:var(--ui-muted,#6b6b6b);
  word-break:break-word;
}
.uc-msg b{color:var(--ui-text,#1a1a1a);}
.uc-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:4px;}
.uc-btn{
  height:32px;padding:0 16px;border-radius:8px;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;
  transition:background .16s,opacity .16s;
}
.uc-btn:hover{background:var(--ui-hover);}
.uc-btn.uc-ok{
  border-color:transparent;
  background:var(--ui-accent-solid,#0969da);color:var(--ui-on-accent,#fff);
}
.uc-btn.uc-ok:hover{opacity:.88;background:var(--ui-accent-solid,#0969da);}
.uc-btn.uc-danger{
  border-color:transparent;
  background:var(--ui-danger,#d1242f);color:#fff;
}
.uc-btn.uc-danger:hover{opacity:.88;background:var(--ui-danger,#d1242f);}
`;

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

/** 转义，message 里可能带模型名 */
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/**
 * 弹确认框。
 * @param {{title?:string, message?:string, okText?:string, cancelText?:string, danger?:boolean}} o
 * @returns {Promise<boolean>} 点确定 true；取消 / Esc / 点蒙版 false
 */
export function confirmDialog(o) {
  const opt = o || {};
  injectStyle();

  return new Promise((resolve) => {
    const mask = document.createElement('div');
    mask.className = 'uc-mask';
    mask.innerHTML = `
      <div class="uc-panel" role="dialog" aria-modal="true">
        <div class="uc-title">${esc(opt.title || '确认操作')}</div>
        <div class="uc-msg">${opt.messageHtml || esc(opt.message || '')}</div>
        <div class="uc-foot">
          <button class="uc-btn" type="button" data-cancel>${esc(opt.cancelText || '取消')}</button>
          <button class="uc-btn ${opt.danger ? 'uc-danger' : 'uc-ok'}" type="button" data-ok>${esc(opt.okText || '确定')}</button>
        </div>
      </div>`;

    const panel = mask.querySelector('.uc-panel');
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      document.removeEventListener('keydown', onKey, true);
      mask.remove();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); finish(false); }
      else if (e.key === 'Enter') { e.stopPropagation(); finish(true); }
    };

    mask.querySelector('[data-ok]').addEventListener('click', () => finish(true));
    mask.querySelector('[data-cancel]').addEventListener('click', () => finish(false));
    mask.addEventListener('mousedown', (e) => { if (!panel.contains(e.target)) finish(false); });
    document.addEventListener('keydown', onKey, true);

    document.body.appendChild(mask);
    const okBtn = mask.querySelector('[data-ok]');
    if (okBtn) okBtn.focus();
  });
}
