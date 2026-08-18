/* DOM 工具：转义 / 创建元素 / 徽章，界面共用，避免各 screen 重复实现。 */

/** HTML 转义（所有插值必须经它，防注入）。 */
export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** 徽章（chip）：ok/err/默认三类，语义色由 base.css 提供。 */
export function chip(text, kind = "") {
  return `<span class="chip ${kind}">${escapeHtml(text)}</span>`;
}

/** 空态占位：界面无数据时的统一展示。 */
export function empty(text = "暂无数据") {
  return `<div class="sub" style="padding:12px 0">${escapeHtml(text)}</div>`;
}

/** 错误态占位：接口失败/后端未连接的统一降级展示。 */
export function errorBox(exc) {
  const msg = exc?.message || String(exc || "未知错误");
  return `<div class="panel err">加载失败：${escapeHtml(msg)}<br><span class="sub">请确认后端已启动（palm.bootstrap.app.build_app + HTTP 适配层）。</span></div>`;
}

/** 状态徽章组：可用/不可用/未知。 */
export function stateChip(enabled) {
  if (enabled === true) return chip("可用", "ok");
  if (enabled === false) return chip("不可用", "err");
  return chip("未知");
}
