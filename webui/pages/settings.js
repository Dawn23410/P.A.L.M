/**
 * 设置模块
 * ========
 * 提供「外观」等设置子页面。子页面采用与侧边栏一致的模块化架构：
 * 每个二级子菜单是独立模块（PANE_DEFS），拥有自己的 DOM 容器与加载逻辑，
 * 加载失败只在该子页面内显示错误兜底，不波及顶部栏、其他子页面与外壳。
 *
 * 主题的唯一真相源是 core/theme/index.js。
 */

import { mountModelSection } from './models.js';

const STYLE_ID = 'mod-settings-style';
const CSS = `
.mod-settings{
  height:100%;overflow:auto;
  background:var(--ui-bg,#fff);
  color:var(--ui-text,#1a1a1a);
  padding:0 32px 40px;                /* 顶部 padding 清零：让顶部导航栏能真正贴到主界面顶端 */
  transition:background .2s ease,color .2s ease;
}
/* 设置内容左对齐铺满主区域（此前是居中收束成 760px 一列，宽屏下两侧留白过多）。 */
.mod-settings .s-panes{ margin:0; }
.mod-settings .s-group{ max-width:none; }
.mod-settings .s-label{
  font-size:0.8571rem;font-weight:600;color:var(--ui-muted,#6b6b6b);
  letter-spacing:.4px;text-transform:uppercase;margin-bottom:10px;
}
/* 三个主题卡恒定单行排列：minmax(0,1fr) 保证窄屏时等比收缩而不是换行 */
.mod-settings .s-cards{ display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px; }
.mod-settings .s-card{
  border:1px solid var(--ui-border,#e0e0e0);
  border-radius:var(--ui-radius,10px);background:var(--ui-elev,#fff);
  padding:14px 14px 16px;cursor:pointer;
  display:flex;flex-direction:column;gap:8px;align-items:flex-start;
  font-family:inherit;font-size:0.9286rem;color:var(--ui-text,#1a1a1a);
  transition:border-color .16s,background .16s,box-shadow .16s,transform .16s var(--ui-ease);
  text-align:left;
}
.mod-settings .s-card:hover{
  background:var(--ui-hover);
  transform:translateY(-1px);
  box-shadow:var(--ui-shadow-2,0 6px 20px -6px rgba(0,0,0,.12));
}
.mod-settings .s-card.on{
  border-color:var(--ui-accent,#0969da);
  box-shadow:0 0 0 2px color-mix(in srgb,var(--ui-accent,#0969da) 22%,transparent);
}
.mod-settings .s-card svg{
  width:18px;height:18px;stroke:currentColor;fill:none;
  stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;
}
.mod-settings .s-card .cap{font-weight:600;}
.mod-settings .s-card .desc{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);line-height:1.5;
}

/* ---------- 字号（外观页内：一行式 字号 [滑条] [细调] 数值） ---------- */
.mod-settings .s-font-group{ margin-top:18px; }
.mod-settings .s-fontrow{ display:flex; align-items:center; gap:12px; }
.mod-settings .s-fontname{
  flex:none;font-size:0.9286rem;color:var(--ui-text,#1a1a1a);
}
.mod-settings .s-frange{
  flex:1 1 auto;min-width:160px;max-width:280px;
  accent-color:var(--ui-accent,#0969da);
}
.mod-settings .s-fbtn{
  flex:none;width:26px;height:26px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);cursor:pointer;
  font-size:1rem;line-height:1;color:var(--ui-text,#1a1a1a);
  user-select:none;-webkit-user-select:none;transition:background .16s;
}
.mod-settings .s-fbtn:hover{ background:var(--ui-hover); }
.mod-settings .s-fval{
  flex:none;min-width:44px;text-align:right;
  font-size:0.9286rem;color:var(--ui-text,#1a1a1a);
  font-variant-numeric:tabular-nums;
}

/* ---------- 字体（外观页内：一行式 字体 [下拉]） ---------- */
.mod-settings .s-fselect{
  flex:none;min-width:160px;height:28px;padding:0 8px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;cursor:pointer;
}

/* ---------- 聊天子页面分段 ---------- */
.mod-settings .s-pane .s-group + .s-group{ margin-top:24px; }
.mod-settings .s-model-head{
  display:flex;align-items:center;justify-content:space-between;
  margin-bottom:10px;
}
.mod-settings .s-model-head .s-label{ margin-bottom:0; }
.mod-settings .s-model-add{
  height:28px;padding:0 12px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);font-family:inherit;
  font-size:0.8571rem;color:var(--ui-text,#1a1a1a);cursor:pointer;
  transition:background .16s;
}
.mod-settings .s-model-add:hover{ background:var(--ui-hover); }
.mod-settings .s-model-list{
  max-height:220px;overflow-y:auto;
  border:1px solid var(--ui-border-soft,#ececec);border-radius:10px;
  background:var(--ui-elev,#fff);
  /* 滚动能力保留、滚动条隐藏 */
  scrollbar-width:none;-ms-overflow-style:none;
}
.mod-settings .s-model-list::-webkit-scrollbar{ display:none; width:0; height:0; }
.mod-settings .s-model-empty{
  padding:24px;text-align:center;
  font-size:0.8571rem;color:var(--ui-faint,#9a9a9a);
}

/* ---------- 聊天子页面：行为开关（设置项模块化，独立失败隔离） ---------- */
.mod-settings .s-toggle{
  display:flex;align-items:flex-start;gap:10px;
  padding:12px 0;border-top:1px solid var(--ui-border-soft,#ececec);
  cursor:pointer;
}
.mod-settings .s-toggle:first-of-type{border-top:none;padding-top:4px;}
.mod-settings .s-toggle input{
  margin-top:2px;width:16px;height:16px;flex:none;
  accent-color:var(--ui-accent,#0969da);cursor:pointer;
}
.mod-settings .s-toggle-main{display:flex;flex-direction:column;gap:2px;}
.mod-settings .s-toggle-title{font-size:0.9286rem;font-weight:600;color:var(--ui-text,#1a1a1a);}
.mod-settings .s-toggle-desc{font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);line-height:1.5;}

/* ---------- 顶部导航栏：与侧边栏同色号、同交互逻辑 ---------- */
.mod-settings .s-topbar{
  height:40px;                       /* 调高：容纳导航 tab */
  margin:0 -32px 14px;               /* .mod-settings 顶 padding 已清零，栏直接落 y=0 贴主界面顶 */
  background:var(--ui-panel,#f5f5f5);/* 与侧边栏 panel 同色号 */
  border-radius:0;                   /* 平贴顶端，无圆角 */
  position:sticky; top:0; z-index:2;   /* 滚动时常驻顶部 */
  display:flex; align-items:center;
  padding:0 12px;
  overflow:hidden;
}
.mod-settings .s-tabs{
  display:flex; align-items:center; gap:4px; height:100%;
}
.mod-settings .s-tab{
  height:28px; padding:0 14px;
  border:none; outline:none; background:transparent; cursor:pointer;
  border-radius:7px; font-family:inherit; font-size:0.9286rem; font-weight:400;  /* 未选中不加粗 */
  color:var(--ui-muted,#6b6b6b);
  user-select:none; -webkit-user-select:none;
  transition:background .16s,color .16s;
}
.mod-settings .s-tab:hover{ background:var(--ui-hover); color:var(--ui-text); }   /* 悬停：背景变化，字体不加粗 */
.mod-settings .s-tab.on{ background:var(--ui-active); color:var(--ui-text); font-weight:600; } /* 选中：加粗 + 背景 */

.mod-settings .s-pane{ display:none; }
.mod-settings .s-pane.on{ display:block; }

/* ---------- 子页面加载失败兜底（仅影响自身容器） ---------- */
.mod-settings .s-pane-error{
  height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:14px;padding:40px;text-align:center;
}
.mod-settings .s-pane-error-head{ display:flex;align-items:center;gap:8px;font-size:1rem;color:var(--ui-danger); }
.mod-settings .s-pane-error-dot{ width:8px;height:8px;border-radius:50%;background:var(--ui-danger);flex:0 0 8px; }
.mod-settings .s-pane-error-msg{
  max-width:80%;max-height:40%;overflow:auto;
  font-family:ui-monospace,Consolas,monospace;font-size:0.8571rem;line-height:1.6;
  color:var(--ui-muted);background:var(--ui-panel);border:1px solid var(--ui-border-soft);
  border-radius:8px;padding:12px 14px;text-align:left;white-space:pre-wrap;word-break:break-word;
}
.mod-settings .s-pane-error-btn{
  height:32px;padding:0 16px;border:1px solid var(--ui-border);border-radius:8px;
  background:var(--ui-elev);font-family:inherit;font-size:0.8571rem;color:var(--ui-text);cursor:pointer;
  transition:background .16s;
}
.mod-settings .s-pane-error-btn:hover{ background:var(--ui-hover); }

/* 顶部标签栏与内容同为左对齐，起于同一条竖线 */
.mod-settings .s-topbar .s-tabs{ width:100%; margin:0; }

/* ---------- 自适应 ---------- */
/* 注意：.s-topbar 用负 margin 抵消 .mod-settings 的左右 padding，
   改 padding 必须同步改这里的负 margin，否则栏会溢出或短一截。 */
@media (max-width:1180px){
  .mod-settings{ padding:0 24px 32px; }
  .mod-settings .s-topbar{ margin:0 -24px 14px; }
}
@media (max-width:860px){
  .mod-settings{ padding:0 18px 28px; }
  .mod-settings .s-topbar{ margin:0 -18px 14px; }
}
@media (max-width:560px){
  .mod-settings{ padding:0 14px 24px; }
  .mod-settings .s-topbar{ margin:0 -14px 14px; }
  .mod-settings .s-fontrow{ flex-wrap:wrap; row-gap:8px; }
  .mod-settings .s-frange{ max-width:none; }
}
`;

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();          // 热重载时用最新样式
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

const ICON = {
  light: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l1.6 1.6M6.9 17.1l1.6 1.6"/>',
  dark: '<path d="M20.5 14.6A8.6 8.6 0 0 1 9.4 3.5a8.6 8.6 0 1 0 11.1 11.1z"/>',
  system: '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M9 20.5h6M12 16.5v4"/>',
};

const OPTIONS = [
  { key: 'light', cap: '亮色', desc: '始终使用明亮配色' },
  { key: 'dark', cap: '暗色', desc: '始终使用深色配色' },
  { key: 'system', cap: '跟随系统', desc: '随系统外观自动切换' },
];

/** 二级子菜单注册表：每个子页面独立、可隔离失败（学习侧边栏的模块化架构） */
const PANE_DEFS = {
  appearance: { title: '外观', mount: mountAppearance },
  chat: { title: '聊天', mount: mountChat },
};

/* ---------- 聊天子页面：行为 / 显示 / 模型 三段式，开关实时写入并广播 ---------- */
function readChatPref(key, def) {
  try {
    const raw = localStorage.getItem('webui.chat.' + key);
    return raw === null ? def : (raw === '1' || raw === 'true');
  } catch (e) { return def; }
}

const toggleRow = (key, title, desc) => `
  <label class="s-toggle">
    <input type="checkbox" data-pref="${key}" />
    <span class="s-toggle-main">
      <span class="s-toggle-title">${title}</span>
      <span class="s-toggle-desc">${desc}</span>
    </span>
  </label>`;

function mountChat(container) {
  container.innerHTML = `
    <div class="s-group">
      <div class="s-label">行为设置</div>
      ${toggleRow('enterSend', '回车发送消息', '回车 = 发送，Shift + 回车 = 换行；关闭后回车仅换行')}
    </div>
    <div class="s-group">
      <div class="s-label">显示设置</div>
      ${toggleRow('showTokenStats', '显示 Token 统计', '回复下方显示 输入 / 缓存命中 / 输出 / 总计 token')}
      ${toggleRow('showDetailInfo', '显示详细信息', '首字延迟、输出速度、耗时、请求 ID、请求时间')}
    </div>
    <div class="s-group" data-model-section></div>`;

  const modelApi = mountModelSection(container.querySelector('[data-model-section]'));

  const boxes = Array.from(container.querySelectorAll('input[data-pref]'));
  const apply = () => boxes.forEach((b) => { b.checked = readChatPref(b.dataset.pref, true); });
  const onChange = (e) => {
    const b = e.target.closest('input[data-pref]');
    if (!b) return;
    try { localStorage.setItem('webui.chat.' + b.dataset.pref, b.checked ? '1' : '0'); } catch (e2) {}
    window.dispatchEvent(new CustomEvent('webui:chat-pref', { detail: { key: b.dataset.pref, val: b.checked } }));
  };
  container.addEventListener('change', onChange);
  apply();

  return {
    destroy() {
      container.removeEventListener('change', onChange);
      modelApi.destroy();
      container.innerHTML = '';
    },
  };
}

/* ---------- 全局字号：唯一可调字号，作用于根 --ui-root-font-size ---------- */
const FONT_KEY = 'webui.font.global';
const FONT_DEFAULT = 14;
const FONT_MIN = 10;                 // 范围自定：10–19px，默认 14
const FONT_MAX = 19;

function readFontPx() {
  // ⚠️ 不能直接 Number(getItem())：键不存在时 getItem 返回 null，
  // 而 Number(null) === 0（不是 NaN），会被 isFinite 放行、再被夹紧成
  // FONT_MIN，导致全新用户一打开就是 10px（比默认的 14px 小 40%）。
  // 必须先判 null 再判数字。
  const raw = localStorage.getItem(FONT_KEY);
  if (raw === null || raw === '') return FONT_DEFAULT;
  const v = Number(raw);
  if (!Number.isFinite(v)) return FONT_DEFAULT;
  return Math.max(FONT_MIN, Math.min(FONT_MAX, v));   // 已存值超界时夹紧，不静默重置
}

/* ---------- 字体（自管理字体文件：webui/fonts/ 子集 woff2 + @font-face） ----------
 * 每个家族都以系统同款字体兜底：woff2 加载失败时视觉仍然成立。
 * 子集字符集 = ASCII + GB2312 全区 + 常用标点（生成脚本 _make_webfonts.py）。 */
const FONT_FAMILY_KEY = 'webui.font.family';
const FONT_FAMILIES = [
  { key: 'sys',  label: '系统默认', stack: '' },
  { key: 'song', label: '宋体', stack: '"PalmSong","SimSun",serif' },
  { key: 'fang', label: '仿宋', stack: '"PalmFang","FangSong","SimSun",serif' },
  { key: 'kai',  label: '楷体', stack: '"PalmKai","KaiTi","SimSun",serif' },
  { key: 'hei',  label: '黑体', stack: '"PalmHei","SimHei","Microsoft YaHei",sans-serif' },
  { key: 'mono', label: '等宽', stack: 'ui-monospace,SFMono-Regular,Menlo,Consolas,"Cascadia Code",monospace' },
];

function readFontFamily() {
  try { return localStorage.getItem(FONT_FAMILY_KEY) || ''; } catch (e) { return ''; }
}

function applyFontFamily(str) {
  if (!str) {
    document.documentElement.style.removeProperty('--ui-font-family');
    try { localStorage.removeItem(FONT_FAMILY_KEY); } catch (e) {}
  } else {
    document.documentElement.style.setProperty('--ui-font-family', str);
    try { localStorage.setItem(FONT_FAMILY_KEY, str); } catch (e) {}
  }
}

/** 外观子页面：主题模式（亮 / 暗 / 跟随系统）+ 全局字号 */
function mountAppearance(container) {
  const Theme = window.Theme;
  container.innerHTML = `
    <div class="s-group">
      <div class="s-label">外观 / 主题</div>
      <div class="s-cards">
        ${OPTIONS.map((o) => `
          <button class="s-card" type="button" data-mode="${o.key}">
            <svg viewBox="0 0 24 24" aria-hidden="true">${ICON[o.key]}</svg>
            <span class="cap">${o.cap}</span>
            <span class="desc">${o.desc}</span>
          </button>`).join('')}
      </div>
    </div>
    <div class="s-group s-font-group">
      <div class="s-fontrow">
        <span class="s-fontname">字号</span>
        <input class="s-frange" type="range" min="${FONT_MIN}" max="${FONT_MAX}" step="1" aria-label="全局字号" />
        <button class="s-fbtn" type="button" data-d="-1" aria-label="减小字号">−</button>
        <button class="s-fbtn" type="button" data-d="1" aria-label="增大字号">＋</button>
        <span class="s-fval"></span>
      </div>
      <div class="s-fontrow" style="margin-top:12px;">
        <span class="s-fontname">字体</span>
        <select class="s-fselect" data-fam aria-label="字体"></select>
      </div>
    </div>`;

  const cards = Array.from(container.querySelectorAll('.s-card'));
  const range = container.querySelector('.s-frange');
  const valEl = container.querySelector('.s-fval');
  const famSelect = container.querySelector('[data-fam]');

  function syncCards() {
    const m = Theme ? Theme.mode : 'light';
    cards.forEach((c) => c.classList.toggle('on', c.dataset.mode === m));
  }

  /** 写入并应用全局字号（滑条 step=1，细调按钮 ±1，双路都在此收敛） */
  function setFont(px) {
    px = Math.max(FONT_MIN, Math.min(FONT_MAX, px));
    localStorage.setItem(FONT_KEY, String(px));
    document.documentElement.style.setProperty('--ui-root-font-size', px + 'px');
    range.value = String(px);
    valEl.textContent = px + 'px';
  }

  const onCardClick = (e) => {
    const card = e.target.closest('.s-card');
    if (!card || !Theme) return;
    Theme.set(card.dataset.mode);
  };
  const onFontClick = (e) => {
    const btn = e.target.closest('.s-fbtn');
    if (btn) setFont(readFontPx() + Number(btn.dataset.d));
  };
  const onRangeInput = () => setFont(Number(range.value));

  // 字体：预设下拉（自管理 woff2 家族，写入 --ui-font-family，全站经 inherit 跟随）
  famSelect.innerHTML = FONT_FAMILIES.map((f) => `<option value="${f.key}">${f.label}</option>`).join('');
  function syncFam() {
    const cur = readFontFamily();
    const hit = FONT_FAMILIES.find((f) => f.stack === cur);
    if (hit) { famSelect.value = hit.key; }
    else { applyFontFamily(''); famSelect.value = 'sys'; }   // 旧版存值/已删自定义：清洗回落系统默认
  }
  const onFamSelect = () => {
    const f = FONT_FAMILIES.find((x) => x.key === famSelect.value);
    applyFontFamily(f ? f.stack : '');
    syncFam();
  };
  famSelect.addEventListener('change', onFamSelect);

  container.addEventListener('click', onCardClick);
  container.addEventListener('click', onFontClick);
  range.addEventListener('input', onRangeInput);
  const off = Theme ? Theme.onChange(syncCards) : null;

  // 进入时恢复已保存的全局字号与字体
  setFont(readFontPx());
  syncFam();
  syncCards();

  return {
    destroy() {
      if (off) off();
      container.removeEventListener('click', onCardClick);
      container.removeEventListener('click', onFontClick);
      range.removeEventListener('input', onRangeInput);
      container.innerHTML = '';
    },
  };
}

/** 子页面加载失败兜底（仅影响该子页面自身容器），提供重试 */
function renderPaneError(el, id, err, retry) {
  const msg = (err && (err.stack || err.message)) || String(err);
  el.innerHTML = `
    <div class="s-pane-error">
      <div class="s-pane-error-head">
        <span class="s-pane-error-dot"></span>
        <strong>子页面「${id}」加载失败</strong>
      </div>
      <pre class="s-pane-error-msg">${escapeHtml(msg)}</pre>
      <button class="s-pane-error-btn" type="button">重试</button>
    </div>`;
  const btn = el.querySelector('.s-pane-error-btn');
  if (btn) btn.addEventListener('click', () => { el.innerHTML = ''; if (retry) retry(); });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

export default function mount(host) {
  injectStyle();
  const paneApis = {};

  host.innerHTML = `
    <div class="mod-settings">
      <div class="s-topbar">
        <div class="s-tabs">
          ${Object.entries(PANE_DEFS).map(([id, def]) => `
            <button class="s-tab" type="button" data-pane="${id}">${def.title}</button>`).join('')}
        </div>
      </div>
      <div class="s-panes">
        ${Object.keys(PANE_DEFS).map((id) => `
          <div class="s-pane" data-pane="${id}"></div>`).join('')}
      </div>
    </div>`;

  const tabs = Array.from(host.querySelectorAll('.s-tab'));
  const panes = Array.from(host.querySelectorAll('.s-pane'));

  function activatePane(id) {
    // 强制单选：永远恰好一个子页面处于选中态，不可全部取消
    tabs.forEach((t) => t.classList.toggle('on', t.dataset.pane === id));
    panes.forEach((p) => p.classList.toggle('on', p.dataset.pane === id));
  }

  function safeMountPane(id, el) {
    // 独立 try/catch：某子页面炸了，只有它自己显示错误兜底
    try {
      const def = PANE_DEFS[id];
      if (!def) return;
      paneApis[id] = def.mount(el) || {};
    } catch (err) {
      renderPaneError(el, id, err, () => { el.innerHTML = ''; safeMountPane(id, el); });
      paneApis[id] = {};
    }
  }

  const onClick = (e) => {
    const tab = e.target.closest('.s-tab');
    if (tab) activatePane(tab.dataset.pane);   // 卡片交互交给各子页面自己处理
  };

  // 逐子页面独立挂载（失败隔离）
  Object.keys(PANE_DEFS).forEach((id) => {
    const el = host.querySelector(`.s-pane[data-pane="${id}"]`);
    if (el) safeMountPane(id, el);
  });

  // 默认进入第一个子页面（外观）
  const first = Object.keys(PANE_DEFS)[0];
  if (first) activatePane(first);

  host.addEventListener('click', onClick);

  return {
    onShow() {},
    onHide() {},
    destroy() {
      Object.values(paneApis).forEach((api) => {
        if (api && typeof api.destroy === 'function') {
          try { api.destroy(); } catch (_) { /* 忽略单个子页面的销毁错误 */ }
        }
      });
      host.removeEventListener('click', onClick);
      host.innerHTML = '';
    },
  };
}
