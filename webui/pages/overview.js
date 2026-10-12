/**
 * 概况模块（空白占位页）
 * ======================
 * 之前的「架构可视化」设计已归档到 `_archive/overview-design-20260929/`。
 * 这里恢复为最初的占位页：居中显示「概况 / 暂无可展示的内容」。
 *
 * 生命周期：mount(host) -> { onShow, onHide, destroy }
 */

const STYLE_ID = 'mod-overview-style';

const CSS = `
.mod-overview{
  height:100%;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:8px;padding:32px;text-align:center;
  color:var(--ui-text,#1a1a1a);
}
.mod-overview .o-title{
  font-size:1.4286rem;font-weight:600;line-height:1.3;
  letter-spacing:-.2px;color:var(--ui-text,#1a1a1a);
}
.mod-overview .o-desc{
  max-width:46ch;
  font-size:0.9286rem;line-height:1.75;
  color:var(--ui-faint,#9a9a9a);
}
`;

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

export default function mount(host) {
  injectStyle();

  host.innerHTML = `
    <div class="mod-overview">
      <div class="o-title">概况</div>
      <div class="o-desc">暂无可展示的内容</div>
    </div>`;

  return {
    onShow() {},
    onHide() {},
    destroy() {
      host.innerHTML = '';
    },
  };
}
