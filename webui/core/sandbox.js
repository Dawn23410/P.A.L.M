/**
 * 页面沙箱容器（DOM 隔离）
 * =========================
 * 每个页面独享一个根节点（.mod-host），互不干扰；
 * 任一页面抛错，只影响它自己的容器，不波及外壳与其他页面。
 *
 * 注意：本文件只负责「DOM 子树隔离 + 错误界面」。
 * 页面的加载 / 卸载 / 生命周期回滚已交给底层框架 kernel
 * （见 core/page-plugin.js + core/loader.js），这里不再重复。
 */

/** 页面加载失败时展示的兜底界面 */
export function renderError(host, id, err) {
  const msg = (err && (err.stack || err.message)) || String(err);
  host.innerHTML = `
    <div class="mod-error">
      <div class="mod-error-head">
        <span class="mod-error-dot"></span>
        <strong>页面「${id}」加载失败</strong>
      </div>
      <pre class="mod-error-msg">${escapeHtml(msg)}</pre>
      <button class="mod-error-btn" type="button">重新加载</button>
    </div>`;
  const btn = host.querySelector('.mod-error-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      host.dispatchEvent(
        new CustomEvent('mod:reload', { bubbles: true, detail: { id } })
      );
    });
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

/**
 * 为某个页面创建一个隔离的容器元素。
 * 每个页面独享一个根节点，互不干扰。
 */
export function createSandbox(id) {
  const host = document.createElement('section');
  host.className = 'mod-host';
  host.dataset.modId = id;
  return host;
}
