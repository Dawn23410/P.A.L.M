/**
 * 概况模块 —— 模块驱动的架构可视化（矢量 SVG + 原生缩放）
 * ==========================================================
 * 结构（纯前端应用，只有一个前端分支）：
 *   CPU 核心处理器（居中在上）
 *     └── 前端（二级球）
 *           └── 全部模块（页面模块 + 基础设施：渲染器/日志/主题/路由/加载器）横排在下
 *
 * 尺寸（按层级）：CPU 25 / 前端 18 / 模块 10~14
 * 连接：由层级自动生成，每条连接 = 2 根分开的平行线（透明）
 * 视觉：球为浅蓝，无投影
 *
 * 缩放/平移：变换施加在 **SVG 内部 <g>** 上（矢量原生，放大清晰）
 * 节点三态：未检测到=不渲染；检测到但心跳不通=半透明虚线轮廓；心跳通=浅蓝实心球
 *
 * 生命周期：mount(host) -> { onShow, onHide, destroy }（mount 为 async）
 */

import { log } from '../core/log.js';
import { buildModel } from '../core/manifest.js';

const STYLE_ID = 'mod-overview-style';

/* ---------- 逻辑画布 / 尺寸 / 布局 ---------- */
const VW = 1000, VH = 600;
const R_ROOT = 25, R_BRANCH = 18;
const CPU_POS = { x: 500, y: 118 };      // CPU 居中在上
const BR_POS = { x: 500, y: 320 };       // 前端
const CHILD_Y = 480;                     // 模块横排
const CHILD_X0 = 110, CHILD_X1 = 890;    // 横排左右边界
const OFFSET = 12;                       // 每条连接的 2 根线的间距

const HEARTBEAT_MS = 5000;
const SPEED_PX_PER_MS = 0.135;
const FRAME_MAX_MS = 50;

const PACKET_TYPES = [
  { type: 'control',   label: '控制指令', color: '#5b8cff' },
  { type: 'render',    label: '渲染任务', color: '#2dd4bf' },
  { type: 'state',     label: '状态同步', color: '#f5b133' },
  { type: 'event',     label: '事件回调', color: '#f472b6' },
  { type: 'heartbeat', label: '心跳检测', color: '#a78bfa' },
  { type: 'warn',      label: '警告',     color: '#fb923c' },
  { type: 'error',     label: '错误',     color: '#ef4444' },
];

const CSS = `
.mod-overview{
  position:relative;width:100%;height:100%;overflow:hidden;
  background:var(--ui-bg,#fff);color:var(--ui-text,#1a1a1a);
  display:flex;flex-direction:column;
  --ov-font:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
}
.mod-overview{
  --ov-ink:#28334a; --ov-muted:#8b94a6;
  --ov-ball-hi:#eef5ff; --ov-ball-mid:#c6dcfb; --ov-ball-lo:#93bdf2; --ov-ball-edge:#7fb0ff;
  --ov-line:rgba(120,160,220,.30);
  --ov-idle:#9aa3b2;
  --ov-grid:rgba(40,60,92,.05);
  --ov-vignette:rgba(91,140,255,.06);
  --ov-hair:rgba(40,60,92,.10);
}
html[data-theme="dark"] .mod-overview{
  --ov-ink:#e7edf8; --ov-muted:#8b95a8;
  --ov-ball-hi:#3f5a92; --ov-ball-mid:#213256; --ov-ball-lo:#0d1626; --ov-ball-edge:#8ab6ff;
  --ov-line:rgba(140,175,240,.22);
  --ov-idle:#7c8698;
  --ov-grid:rgba(120,150,220,.06);
  --ov-vignette:rgba(80,130,255,.10);
  --ov-hair:rgba(150,180,240,.14);
}

.mod-overview .ov-head{flex:none;display:flex;align-items:center;gap:14px;padding:18px 30px 0;}
.mod-overview .ov-eyebrow{
  font-size:11px;font-weight:600;letter-spacing:.2em;text-transform:uppercase;
  color:var(--ov-muted);font-family:var(--ov-font);white-space:nowrap;
}
.mod-overview .ov-hr{flex:1;height:1px;background:linear-gradient(90deg,var(--ov-hair),transparent);}
.mod-overview .ov-reset{
  flex:none;border:1px solid var(--ov-hair);background:transparent;color:var(--ov-muted);
  font:inherit;font-size:10.5px;letter-spacing:.02em;padding:3px 10px;border-radius:7px;cursor:pointer;
  transition:background .15s,color .15s;
}
.mod-overview .ov-reset:hover{background:var(--ui-hover,rgba(0,0,0,.05));color:var(--ov-ink);}

.mod-overview .ov-window{
  flex:1;min-height:0;position:relative;overflow:hidden;
  cursor:grab;touch-action:none;user-select:none;-webkit-user-select:none;overscroll-behavior:contain;
}
.mod-overview .ov-window.grabbing{cursor:grabbing;}
.mod-overview .ov-svg{width:100%;height:100%;display:block;}

.mod-overview .ov-ball{stroke:var(--ov-ball-edge);stroke-width:1;}
.mod-overview .ov-spec{fill:#ffffff;opacity:.5;}
.mod-overview .ov-idle{fill:none;stroke:var(--ov-idle);stroke-width:1.2;stroke-dasharray:3 3;opacity:.55;}
.mod-overview .ov-node.is-idle .ov-ball,
.mod-overview .ov-node.is-idle .ov-spec{display:none;}
.mod-overview .ov-node:not(.is-idle) .ov-idle{display:none;}

.mod-overview .ov-label{
  fill:var(--ov-ink);font-size:8px;font-weight:600;letter-spacing:.01em;font-family:var(--ov-font);
}
.mod-overview .ov-label.sm{font-size:6px;font-weight:500;fill:var(--ov-ink);}
.mod-overview .ov-node.is-idle .ov-label{opacity:.7;}

.mod-overview .ov-line{fill:none;stroke:var(--ov-line);stroke-width:1.3;stroke-linecap:round;}
.mod-overview .ov-packet{pointer-events:none;}

.mod-overview .ov-foot{
  flex:none;padding:4px 30px 16px;font-size:10.5px;letter-spacing:.02em;color:var(--ov-muted);line-height:1.7;
}
.mod-overview .ov-legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:6px;}
.mod-overview .ov-lg{display:inline-flex;align-items:center;gap:6px;font-size:10px;color:var(--ov-muted);}
.mod-overview .ov-lg i{width:8px;height:8px;border-radius:50%;display:inline-block;box-shadow:0 0 6px currentColor;}

@media (prefers-reduced-motion:reduce){}
`;

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/* ---------- 路径工具 ---------- */
function makePath(pts) {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
  }
  return { pts, cum, len: cum[cum.length - 1] || 1 };
}
function offsetPolyline(pts, d) {
  if (pts.length < 2) return pts;
  return pts.map((p, i) => {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    let tx = b.x - a.x, ty = b.y - a.y;
    const L = Math.hypot(tx, ty) || 1; tx /= L; ty /= L;
    return { x: p.x - ty * d, y: p.y + tx * d };
  });
}
/**
 * 把若干「有向段」拼成一条贴着**偏移线**的连续路径。
 * 段与段在节点处相接：插入该节点中心做桥接（桥接点落在球体内，被球遮住），
 * 于是粒子始终贴着画出来的线走，且在节点处平滑过渡、无可见跳变。
 */
function buildRoute(segs, byId) {
  let pts = [];
  segs.forEach((s, i) => {
    const A = byId[s.from], B = byId[s.to];
    if (!A || !B) return;
    const seg = offsetPolyline([{ x: A.x, y: A.y }, { x: B.x, y: B.y }], OFFSET);
    if (i === 0) pts = seg;
    else { pts.push({ x: A.x, y: A.y }); pts = pts.concat(seg); }
  });
  return makePath(pts);
}

function pointAt(path, f) {
  const target = Math.max(0, Math.min(1, f)) * path.len;
  const cum = path.cum;
  let i = 1;
  while (i < cum.length - 1 && cum[i] < target) i++;
  const denom = cum[i] - cum[i - 1];
  const t = denom > 1e-6 ? (target - cum[i - 1]) / denom : 0;
  const a = path.pts[i - 1], b = path.pts[i];
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}
function pathD(pts) { return 'M' + pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('L'); }

/**
 * 路由：真实流程是「往返」——
 *   前端发起（用户操作）→ 前端 → CPU(处理) → 前端 → 渲染器(渲染)   ['cycle']
 *   CPU 发起（渲染/心跳/错误）→ CPU → 前端 → 渲染器                ['out']
 * 两条路线最终都到达「渲染器」。
 */
function resolveRoute(source, target) {
  if (source === 'fe') return 'cycle';
  return 'out';
}

/* ---------- 节点 ---------- */
function buildNodeGroup(node, alive) {
  const g = svgEl('g', { class: 'ov-node' + (alive ? '' : ' is-idle') });
  const r = node.r;
  g.appendChild(svgEl('circle', { class: 'ov-ball', cx: node.x, cy: node.y, r, fill: 'url(#ov-ball-grad)' }));
  g.appendChild(svgEl('circle', { class: 'ov-idle', cx: node.x, cy: node.y, r }));
  g.appendChild(svgEl('ellipse', {
    class: 'ov-spec', cx: node.x - r * 0.32, cy: node.y - r * 0.36, rx: r * 0.28, ry: r * 0.17,
    transform: `rotate(-32 ${node.x - r * 0.32} ${node.y - r * 0.36})`,
  }));
  const t = svgEl('text', {
    class: 'ov-label' + (node.small ? ' sm' : ''),
    x: node.x, y: node.y, 'text-anchor': 'middle', 'dominant-baseline': 'central',
  });
  t.textContent = node.title;
  g.appendChild(t);
  return g;
}

/* ---------- 组装 ---------- */
function buildModelNodes(model) {
  const children = model.nodes;   // 固定内容：未检测到也显示（只是虚线）
  const n = children.length;

  const nodes = [];
  nodes.push({ id: 'cpu', title: '核心处理器', x: CPU_POS.x, y: CPU_POS.y, r: R_ROOT, small: false });
  nodes.push({ id: 'fe', title: '前端', x: BR_POS.x, y: BR_POS.y, r: R_BRANCH, small: false });
  children.forEach((c, i) => {
    nodes.push({
      ...c,
      x: n === 1 ? BR_POS.x : CHILD_X0 + ((CHILD_X1 - CHILD_X0) * i) / (n - 1),
      y: CHILD_Y,
      small: true,
    });
  });

  return { nodes, children };
}

function buildSvg(model) {
  const svg = svgEl('svg', { class: 'ov-svg', preserveAspectRatio: 'xMidYMid meet' });

  const defs = svgEl('defs');
  const grad = svgEl('radialGradient', { id: 'ov-ball-grad', cx: '34%', cy: '30%', r: '76%' });
  grad.appendChild(svgEl('stop', { offset: '0%',   'stop-color': 'var(--ov-ball-hi)' }));
  grad.appendChild(svgEl('stop', { offset: '52%',  'stop-color': 'var(--ov-ball-mid)' }));
  grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'var(--ov-ball-lo)' }));
  defs.appendChild(grad);

  const pat = svgEl('pattern', { id: 'ov-grid', width: '26', height: '26', patternUnits: 'userSpaceOnUse' });
  pat.appendChild(svgEl('circle', { cx: '1', cy: '1', r: '1', fill: 'var(--ov-grid)' }));
  defs.appendChild(pat);
  const vig = svgEl('radialGradient', { id: 'ov-vig', cx: '50%', cy: '44%', r: '72%' });
  vig.appendChild(svgEl('stop', { offset: '0%', 'stop-color': 'var(--ov-vignette)' }));
  vig.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'transparent' }));
  defs.appendChild(vig);

  PACKET_TYPES.forEach((t) => {
    const pg = svgEl('radialGradient', { id: `ov-pg-${t.type}`, cx: '50%', cy: '50%', r: '50%' });
    pg.appendChild(svgEl('stop', { offset: '0%',   'stop-color': '#ffffff', 'stop-opacity': '.95' }));
    pg.appendChild(svgEl('stop', { offset: '35%',  'stop-color': t.color,   'stop-opacity': '.95' }));
    pg.appendChild(svgEl('stop', { offset: '100%', 'stop-color': t.color,   'stop-opacity': '0' }));
    defs.appendChild(pg);
  });
  svg.appendChild(defs);

  // 背景（固定，铺满视口）
  const bg = svgEl('g', { class: 'ov-bg' });
  bg.appendChild(svgEl('rect', { x: '0', y: '0', width: '100%', height: '100%', fill: 'url(#ov-grid)' }));
  bg.appendChild(svgEl('rect', { x: '0', y: '0', width: '100%', height: '100%', fill: 'url(#ov-vig)' }));
  svg.appendChild(bg);

  // 内容视口（缩放/平移施加在这里 —— SVG 原生，矢量清晰）
  const vp = svgEl('g', { class: 'ov-viewport' });
  svg.appendChild(vp);
  svg.__viewport = vp;

  const { nodes, children } = buildModelNodes(model);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const P = (id) => ({ x: byId[id].x, y: byId[id].y });

  // 自动连线：CPU→前端，前端→各模块；每条 2 根分开的线
  const edges = [{ from: 'cpu', to: 'fe' }];
  children.forEach((c) => edges.push({ from: 'fe', to: c.id }));

  const wireG = svgEl('g', { class: 'ov-lines' });
  edges.forEach((e) => {
    const c = [P(e.from), P(e.to)];
    wireG.appendChild(svgEl('path', { class: 'ov-line', d: pathD(offsetPolyline(c, +OFFSET)) }));
    wireG.appendChild(svgEl('path', { class: 'ov-line', d: pathD(offsetPolyline(c, -OFFSET)) }));
  });
  vp.appendChild(wireG);

  // 路线贴着「画出来的偏移线」走（buildRoute 会在节点处用球心桥接，被球遮住）。
  const rndId = byId['renderer'] ? 'renderer' : 'fe';   // 终点=渲染器（没有则退化为前端）
  const routePaths = {
    cycle: buildRoute([{ from: 'fe', to: 'cpu' }, { from: 'cpu', to: 'fe' }, { from: 'fe', to: rndId }], byId),
    out:   buildRoute([{ from: 'cpu', to: 'fe' }, { from: 'fe', to: rndId }], byId),
  };

  const packetG = svgEl('g', { class: 'ov-packets' });
  vp.appendChild(packetG);

  const nodeG = svgEl('g', { class: 'ov-nodes' });
  const stateNodes = [];
  nodes.forEach((n) => {
    const isRoot = n.id === 'cpu';
    const isBranch = n.id === 'fe';
    const g = buildNodeGroup(n, isRoot || isBranch);
    nodeG.appendChild(g);
    if (isRoot) stateNodes.push({ g, id: n.id, kind: 'root', beat: async () => true });
    else if (isBranch) stateNodes.push({ g, id: n.id, kind: 'branch', childIds: children.map((c) => c.id), beat: async () => true });
    else stateNodes.push({ g, id: n.id, kind: 'child', detected: n.detected, beat: n.beat });
  });
  vp.appendChild(nodeG);
  svg.__stateNodes = stateNodes;

  svg.__stream = startStream(packetG, routePaths);
  return svg;
}

/** 心跳：子球能否拉起 → 活(实心) / 未活(半透明)；前端=任一子球活；CPU 恒活 */
async function refreshStates(svg) {
  const sn = svg.__stateNodes || [];
  const ok = {};
  await Promise.all(
    sn.filter((n) => n.kind === 'child').map(async (n) => {
      if (!n.detected) { ok[n.id] = false; return; }   // 未检测到 → 虚线（不再隐藏）
      try { ok[n.id] = !!(await n.beat()); } catch { ok[n.id] = false; }
    })
  );
  sn.forEach((n) => {
    let alive;
    if (n.kind === 'root') alive = true;
    else if (n.kind === 'branch') alive = (n.childIds || []).some((c) => ok[c]);
    else alive = !!ok[n.id];
    n.g.classList.toggle('is-idle', !alive);
  });
}

function startStream(packetG, routePaths) {
  const reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const packets = [];
  const handled = new Set();
  let raf = 0;

  function emitRecord(rec) {
    let typeName = rec && rec.type;
    if (rec && (rec.level === 'error' || rec.level === 'warn')) typeName = rec.level;
    let idx = PACKET_TYPES.findIndex((t) => t.type === typeName);
    if (idx < 0) idx = PACKET_TYPES.findIndex((t) => t.type === (rec && rec.type));
    if (idx < 0) idx = 0;
    const spec = PACKET_TYPES[idx];
    const routeId = resolveRoute(rec && rec.source, rec && rec.target);
    const path = routePaths[routeId] || routePaths.out;
    const el = svgEl('circle', { class: 'ov-packet', r: 3, fill: `url(#ov-pg-${spec.type})` });
    const p0 = pointAt(path, 0);
    el.setAttribute('cx', p0.x.toFixed(2));
    el.setAttribute('cy', p0.y.toFixed(2));
    packetG.appendChild(el);
    packets.push({ routeId, dist: 0, el });
  }

  const off = log.on((rec) => {
    if (rec && rec.id != null) handled.add(rec.id);
    emitRecord(rec);
  });

  if (reduce) { off(); return { emit() {}, handled, stop() {} }; }

  let lastTick = log.tick();
  function frame(now) {
    const t = log.quantize(now);
    let dtMs = t - lastTick;
    if (dtMs < 0) dtMs = 0;
    if (dtMs > FRAME_MAX_MS) dtMs = FRAME_MAX_MS;
    lastTick = t;
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i];
      const path = routePaths[p.routeId];
      p.dist += SPEED_PX_PER_MS * dtMs;
      if (p.dist >= path.len) { p.el.remove(); packets.splice(i, 1); continue; }
      const pt = pointAt(path, p.dist / path.len);
      p.el.setAttribute('cx', pt.x.toFixed(2));
      p.el.setAttribute('cy', pt.y.toFixed(2));
    }
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    emit: emitRecord,
    handled,
    stop() { cancelAnimationFrame(raf); off(); packets.forEach((p) => p.el.remove()); },
  };
}

/* ---------- 缩放 / 平移（SVG 原生变换 → 矢量清晰） ---------- */
function setupPanZoom(winEl, svg, vp) {
  const view = { x: 0, y: 0, scale: 1 };
  let vpW = 1000, vpH = 600, baseK = 1, minK = 0.2, maxK = 5;
  const PAD = 140;
  const clamp = (v, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));

  function sizeViewBox() {
    vpW = winEl.clientWidth || 1000;
    vpH = winEl.clientHeight || 600;
    svg.setAttribute('viewBox', `0 0 ${vpW} ${vpH}`);
  }
  function apply() {
    vp.setAttribute('transform', `translate(${view.x.toFixed(2)} ${view.y.toFixed(2)}) scale(${view.scale.toFixed(5)})`);
  }
  function clampView() {
    view.x = clamp(view.x, PAD - VW * view.scale, vpW - PAD);
    view.y = clamp(view.y, PAD - VH * view.scale, vpH - PAD);
  }
  function fit() {
    sizeViewBox();
    baseK = Math.min(vpW / VW, vpH / VH) * 0.92;
    minK = baseK * 0.45; maxK = baseK * 3.2;
    view.scale = baseK;
    view.x = (vpW - VW * view.scale) / 2;
    view.y = (vpH - VH * view.scale) / 2;
    apply();
  }

  let rafId = 0;
  const render = () => { rafId = 0; apply(); };
  const schedule = () => { if (!rafId) rafId = requestAnimationFrame(render); };

  function onWheel(e) {
    e.preventDefault();
    const rect = winEl.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    const dir = e.deltaY < 0 ? 1 : -1;
    let k = clamp(view.scale * (1 + 0.12 * dir), minK, maxK);
    const ratio = k / view.scale;
    view.x = px - ratio * (px - view.x);
    view.y = py - ratio * (py - view.y);
    view.scale = k;
    clampView(); schedule();
  }

  let drag = null;
  const DRAG_THRESHOLD = 3;
  function onDown(e) {
    if (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 1) return;
    winEl.setPointerCapture(e.pointerId);
    drag = { sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
    winEl.classList.add('grabbing');
    e.preventDefault();
  }
  function onMove(e) {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    drag.moved = true;
    view.x = drag.ox + dx; view.y = drag.oy + dy;
    clampView(); schedule();
  }
  function onUp(e) {
    if (!drag) return;
    try { winEl.releasePointerCapture(e.pointerId); } catch (_) {}
    drag = null; winEl.classList.remove('grabbing');
  }
  function onDblClick() { fit(); }

  winEl.addEventListener('wheel', onWheel, { passive: false });
  winEl.addEventListener('pointerdown', onDown);
  winEl.addEventListener('pointermove', onMove);
  winEl.addEventListener('pointerup', onUp);
  winEl.addEventListener('pointercancel', onUp);
  winEl.addEventListener('dblclick', onDblClick);

  const onResize = () => { sizeViewBox(); clampView(); schedule(); };
  window.addEventListener('resize', onResize);

  fit();

  return {
    fit,
    destroy() {
      winEl.removeEventListener('wheel', onWheel);
      winEl.removeEventListener('pointerdown', onDown);
      winEl.removeEventListener('pointermove', onMove);
      winEl.removeEventListener('pointerup', onUp);
      winEl.removeEventListener('pointercancel', onUp);
      winEl.removeEventListener('dblclick', onDblClick);
      window.removeEventListener('resize', onResize);
      if (rafId) cancelAnimationFrame(rafId);
    },
  };
}

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

export default async function mount(host) {
  injectStyle();

  const legendHtml = PACKET_TYPES.map(
    (t) => `<span class="ov-lg"><i style="background:${t.color};color:${t.color}"></i>${t.label}</span>`
  ).join('');

  host.innerHTML = `
    <div class="mod-overview" data-root>
      <div class="ov-head">
        <span class="ov-eyebrow">System Architecture</span>
        <span class="ov-hr"></span>
        <button class="ov-reset" type="button" data-reset title="复位视图">复位</button>
      </div>
      <div class="ov-window" data-window></div>
      <div class="ov-foot">
        <div class="ov-legend">${legendHtml}</div>
        滚轮缩放 · 拖拽平移 · 双击复位（矢量 SVG，放大清晰）<br>
        数据流往返：前端 → CPU(处理) → 前端 → 渲染器(渲染)　·　每条连接 2 根线（透明）<br>
        球浅蓝　·　半透明虚线 = 检测到但心跳不通　·　未检测到则不显示
      </div>
    </div>`;

  const model = await buildModel();
  const svg = buildSvg(model);
  const winEl = host.querySelector('[data-window]');
  winEl.appendChild(svg);

  const pz = setupPanZoom(winEl, svg, svg.__viewport);
  host.querySelector('[data-reset]').addEventListener('click', () => pz.fit());

  const stream = svg.__stream;
  const tick = async () => {
    await refreshStates(svg);
    log.info({ source: 'cpu', target: 'fe', type: 'heartbeat' });
  };
  tick();
  const hbTimer = setInterval(tick, HEARTBEAT_MS);

  return {
    onShow() {
      refreshStates(svg);
      if (stream && stream.emit && stream.handled) {
        log.recent(4000).forEach((rec) => {
          if (rec.id != null && stream.handled.has(rec.id)) return;
          if (rec.id != null) stream.handled.add(rec.id);
          stream.emit(rec);
        });
      }
    },
    onHide() {},
    destroy() {
      clearInterval(hbTimer);
      if (stream) stream.stop();
      pz.destroy();
      const style = document.getElementById(STYLE_ID);
      if (style) style.remove();
      host.innerHTML = '';
    },
  };
}
