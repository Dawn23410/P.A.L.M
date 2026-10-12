/**
 * 主页模块
 * 生命周期：mount(host) -> { onShow, onHide, destroy }
 */

const STYLE_ID = 'mod-home-style';
const CSS = `
.mod-home{
  height:100%;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:8px;padding:32px;text-align:center;
  color:var(--ui-text,#1a1a1a);
}
.mod-home .m-title{
  font-size:1.4286rem;font-weight:600;line-height:1.3;
  letter-spacing:-.2px;color:var(--ui-text,#1a1a1a);
}
.mod-home .m-desc{
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
    <div class="mod-home">
      <div class="m-title">主页</div>
      <div class="m-desc">这里是主页</div>
    </div>`;

  return {
    onShow() {},
    onHide() {},
    destroy() {
      host.innerHTML = '';
    },
  };
}
