/**
 * 全局主题管理（亮 / 暗 / 跟随系统）
 * ================================
 *
 * 设计目标：把「配色」这件事从各个页面里抽出来，集中到一处。
 *
 * 三个关键决策：
 *
 *   1. 变量挂在 <html> 上，而不是各页面容器上
 *      —— 侧边栏、顶栏、弹层、Shadow DOM 之外的任何东西都能继承到。
 *
 *   2. 显式 data-theme + color-scheme
 *      —— 前者给 CSS 选择器用，后者让浏览器原生控件（滚动条、表单、
 *         select 下拉）也跟着变色，否则暗色下滚动条还是刺眼的白色。
 *
 *   3. 把主题「广播」给自定义元素（渲染器）
 *      —— 渲染器在 Shadow DOM 里，样式隔离，无法继承外部变量之外的东西。
 *        它们的主题靠 theme 属性驱动，所以这里统一帮它们同步，
 *        页面代码就不必逐个去 setAttribute。
 *
 * 模式（mode）：
 *   'light'  固定亮色
 *   'dark'   固定暗色
 *   'system' 跟随系统 prefers-color-scheme，系统变化时实时响应
 *
 * 持久化：localStorage['webui.theme']
 */

const STORAGE_KEY = 'webui.theme';
const VALID = new Set(['light', 'dark', 'system']);

let mode = 'light';        // 用户选择
let resolved = 'light';    // 实际生效（system 会被解析成 light/dark）
let mql = null;
let bound = false;

const listeners = new Set();

/* ---------- 读取 / 写入 ---------- */

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return VALID.has(v) ? v : null;
  } catch (e) {
    return null;   // 隐私模式等场景下 localStorage 可能不可用
  }
}

function store(v) {
  try { localStorage.setItem(STORAGE_KEY, v); } catch (e) {}
}

/** system 模式解析成具体值 */
function resolveMode(m) {
  if (m === 'system') {
    if (!mql && window.matchMedia) {
      mql = window.matchMedia('(prefers-color-scheme: dark)');
    }
    return (mql && mql.matches) ? 'dark' : 'light';
  }
  return m === 'dark' ? 'dark' : 'light';
}

/* ---------- 应用 ---------- */

/**
 * 把解析后的主题写进 DOM，并广播给订阅者与渲染器元素。
 * 注意：这里只负责「同步状态」，具体视觉全部由 CSS 变量承担。
 */
function apply() {
  const prev = resolved;
  resolved = resolveMode(mode);

  const root = document.documentElement;
  root.setAttribute('data-theme', resolved);
  root.setAttribute('data-theme-mode', mode);
  // 让原生控件（滚动条 / 表单 / select 弹层）跟随
  root.style.colorScheme = resolved;

  // 广播：自定义元素（渲染器）也换装
  if (prev !== resolved) {
    syncElements();
    // 通知渲染器：把颜色固化进 DOM 的产物（Mermaid 图）需要整篇重画。
    // 用事件而不是直接调用，是为了让 core/theme 不必知道渲染器的存在。
    try {
      window.dispatchEvent(new CustomEvent('rnd-theme-change', {
        detail: { theme: resolved, mode },
      }));
    } catch (e) {}
  }

  listeners.forEach((fn) => {
    try { fn(resolved, mode); } catch (e) { console.error('[Theme] listener:', e); }
  });
}

/**
 * 同步所有（含 Shadow DOM 内外）渲染器的 theme 属性。
 *
 * 传入的 tagName 可以是任意自定义元素（md-renderer / 将来的 typst-renderer…），
 * 这里不写死具体标签，凡是实现了 theme 属性的元素都跟随。
 */
function syncElements(scope) {
  const root = scope || document;
  root.querySelectorAll('*').forEach((el) => {
    if (!(el instanceof HTMLElement)) return;
    // 只处理定义了 theme 访问器的 Web Component（渲染器基类提供）
    if (typeof el.theme === 'string') {
      const t = el.theme;
      if (t !== resolved) el.theme = resolved;
    }
  });
}

/* ---------- 对外 API ---------- */

export const Theme = {
  get mode() { return mode; },
  get theme() { return resolved; },
  isDark() { return resolved === 'dark'; },

  /** 设置模式：'light' | 'dark' | 'system' */
  set(m) {
    if (!VALID.has(m)) m = 'light';
    if (m === mode) return resolved;
    mode = m;
    store(m);
    apply();
    return resolved;
  },

  /** 在 light / dark 之间来回切（system 会先落到当前解析值再翻转） */
  toggle() {
    return Theme.set(resolved === 'dark' ? 'light' : 'dark');
  },

  /** 订阅变化，返回取消订阅函数 */
  onChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },

  /** 供页面在插入新渲染器后手动同步一次 */
  sync(scope) { syncElements(scope); },

  /** 初始化（幂等）。index.html 启动时调用一次即可。 */
  init() {
    if (bound) { apply(); return resolved; }
    bound = true;

    mode = readStored() || 'light';
    apply();

    // system 模式下监听系统变化
    if (window.matchMedia) {
      if (!mql) mql = window.matchMedia('(prefers-color-scheme: dark)');
      const onSys = () => { if (mode === 'system') apply(); };
      if (mql.addEventListener) mql.addEventListener('change', onSys);
      else if (mql.addListener) mql.addListener(onSys);
    }

    return resolved;
  },
};

/**
 * 全局 CSS 变量表（按主题分块）。
 *
 * 由 index.html 在启动前内联注入 <style>，避免首屏闪一下白，
 * 所以这里导出的是一段纯 CSS 文本，而不是等模块加载完再插入。
 *
 * 命名约定（页面里统一引用这些，不要再写死颜色）：
 *   --ui-bg          页面底色
 *   --ui-panel       侧边栏 / 卡片等次级面板
 *   --ui-elev        浮层、下拉、按钮底色
 *   --ui-text        主文字
 *   --ui-muted       次要文字
 *   --ui-faint       更弱的提示文字
 *   --ui-border      常规描边
 *   --ui-border-soft 更浅的分隔线
 *   --ui-hover       悬停背景
 *   --ui-active      选中 / 激活背景
 *   --ui-accent      强调色（链接、选中文字）
 *   --ui-shadow      阴影
 */
export const THEME_CSS = `
:root{
  --ui-bg:#ffffff;
  --ui-panel:#f7f8fa;
  --ui-elev:#ffffff;
  --ui-text:#1a1a1a;
  --ui-muted:#6b6b6b;
  --ui-faint:#9a9a9a;
  --ui-border:#e4e6ea;
  --ui-border-soft:#eef0f3;
  --ui-hover:rgba(0,0,0,.05);
  --ui-active:rgba(0,0,0,.08);
  --ui-accent:#0969da;
  --ui-accent-solid:#0969da;
  --ui-on-accent:#fff;
  --ui-shadow:rgba(0,0,0,.07);
  --ui-danger:#b3261e;
  --ui-danger-bg:#fff4f4;
  --ui-danger-border:#f3c7c7;
  --ui-ok:#1a7f37;
  --ui-warn:#9a6700;

  /* ---- 形状 / 动效令牌（与主题无关，统一放这里，页面只认这一套）---- */
  --ui-radius-sm:7px;
  --ui-radius:10px;
  --ui-radius-lg:14px;
  --ui-ease:cubic-bezier(.2,.7,.3,1);
  --ui-shadow-1:0 1px 2px rgba(0,0,0,.04),0 1px 3px rgba(0,0,0,.06);
  --ui-shadow-2:0 6px 20px -6px rgba(0,0,0,.12),0 2px 6px -2px rgba(0,0,0,.06);
}
:root[data-theme='dark']{
  --ui-bg:#12151c;
  --ui-panel:#171b24;
  --ui-elev:#1c212c;
  --ui-text:#e6e9ef;
  --ui-muted:#9aa3b2;
  --ui-faint:#6b7484;
  --ui-border:#2a3040;
  --ui-border-soft:#222736;
  --ui-hover:rgba(255,255,255,.06);
  --ui-active:rgba(255,255,255,.1);
  --ui-accent:#5b8cff;
  --ui-accent-solid:#2b5fd9;
  --ui-on-accent:#fff;
  --ui-shadow:rgba(0,0,0,.4);
  --ui-danger:#ff6b6b;
  --ui-danger-bg:#2a1a1c;
  --ui-danger-border:#5c2b2b;
  --ui-ok:#3fb950;
  --ui-warn:#d29922;
  --ui-shadow-1:0 1px 2px rgba(0,0,0,.4),0 1px 3px rgba(0,0,0,.5);
  --ui-shadow-2:0 8px 24px -8px rgba(0,0,0,.7),0 2px 8px -2px rgba(0,0,0,.5);
}
`;

// ---- 尽早应用，避免首屏闪白 ----
// index.html 的 <head> 里也内联了同样的初始化逻辑（在模块加载前执行），
// 这里再兜一次，保证直接 import 本模块的场景也正确。
(function bootstrap() {
  try {
    mode = readStored() || 'light';
    resolved = resolveMode(mode);
    const root = document.documentElement;
    root.setAttribute('data-theme', resolved);
    root.setAttribute('data-theme-mode', mode);
    root.style.colorScheme = resolved;
  } catch (e) { /* 忽略 */ }
})();

export default Theme;
