/* 界面装载器：shell 与 screen 的唯一契约（UiPort 浏览器侧）。

screen 模块约定（原生 ES Modules，零构建）：
- 每个 screens/<名>/app.js 导出：title(string)、mount(root, ctx)、unmount(root)
- mount 负责渲染到 root；ctx 含 { base, api, dom, chart } 等共享依赖
- 未导出 mount 的目录视为纯文档界面（仅 README）
 */

export const UI_DEPS = {
  api: () => import("./api.js"),
  dom: () => import("./dom.js"),
  chart: () => import("./chart.js"),
};

/** 懒加载并装载一个 screen；返回清理函数。 */
export async function mountScreen(root, name) {
  root.innerHTML = `<div class="sub">装载界面 ${name}…</div>`;
  try {
    const mod = await import(`../screens/${name}/app.js`);
    if (typeof mod.mount !== "function") {
      root.innerHTML = `<div class="sub">界面 ${name} 未提供 mount()（纯文档界面）。</div>`;
      return () => {};
    }
    const ctx = {
      base: (await UI_DEPS.api()).BASE,
      api: await UI_DEPS.api(),
      dom: await UI_DEPS.dom(),
      chart: await UI_DEPS.chart(),
    };
    root.innerHTML = "";
    const cleanup = mod.mount(root, ctx);
    return typeof cleanup === "function" ? cleanup : () => {};
  } catch (exc) {
    root.innerHTML = `<div class="panel err">界面 ${name} 装载失败：${exc.message}<br>` +
      `<span class="sub">请检查 screens/${name}/app.js 语法与导出。</span></div>`;
    return () => {};
  }
}
