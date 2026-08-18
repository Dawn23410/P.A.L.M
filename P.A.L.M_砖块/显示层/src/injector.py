"""注入到每个组件的基座样式与 PALM 桥。

基座样式负责透明、穿透语义、降级语义、自动拖拽把手。
PALM 桥屏蔽 window.pywebview.api 细节，暴露给组件脚本统一的能力。

注意：桥模板用占位符 __WIDGET_ID__，注入时整体 replace，避免 str.format 对 JS 大括号的转义坑。
"""

# 注入到每个组件的基座样式：透明、穿透语义、降级语义、拖拽把手。
BASE_STYLE = """
html, body { margin: 0; padding: 0; background: transparent; overflow: hidden;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
body.click-through { pointer-events: none; }
body.demoted * { animation: none !important; transition: none !important;
  backdrop-filter: none !important; filter: none !important; }
.palm-drag-handle { position: fixed; top: 2px; right: 2px; width: 16px; height: 16px;
  display: flex; align-items: center; justify-content: center; font-size: 11px;
  color: rgba(255,255,255,.6); background: rgba(0,0,0,.25); border-radius: 4px;
  cursor: move; opacity: 0; transition: opacity .15s; z-index: 9999; }
body:hover > .palm-drag-handle { opacity: .8; }
.drag-handle { cursor: move; }
body.locked .palm-drag-handle { display: none; }
::-webkit-scrollbar { width: 0; height: 0; display: none; }
* { scrollbar-width: none; -ms-overflow-style: none; }
"""

# 注入到每个组件的 PALM 桥（用 __WIDGET_ID__ 占位，注入时 replace）。
SHIM_TEMPLATE = """
window.__WIDGET_ID__ = "__WIDGET_ID__";
(function(){
  var api = window.pywebview.api || null;
  var wid = window.__WIDGET_ID__;
  var onCbs = {};
  var pendingSubs = [];
  var flushTimer = null;
  // pywebview 在页面 load 后才注入 window.pywebview.api 并触发 pywebviewready；
  // 组件脚本同步执行时 api 可能尚未就绪，故每次调用都重新读取，并对订阅做就绪后补注册。
  function safeApi(){ return window.pywebview.api || api; }
  function tryFlush(){
    var a = safeApi();
    if(!a) return;
    pendingSubs.forEach(function(p){ a.subscribe(wid, p); });
    pendingSubs = [];
    if(flushTimer){ clearInterval(flushTimer); flushTimer = null; }
  }
  document.addEventListener('pywebviewready', function(){ api = window.pywebview.api; tryFlush(); });
  window.PALM = {
    devicePixelRatio: window.devicePixelRatio || 1,
    providers: { get: function(n){ var a=safeApi(); return a ? a.get_provider(wid, n || "*") : Promise.resolve(null); } },
    onTick: function(ms, cb){ setInterval(function(){ var a=safeApi(); if(a) a.get_provider(wid, "*").then(cb).catch(function(){}); }, ms); },
    on: function(provider, cb){
      (onCbs[provider] = onCbs[provider] || []).push(cb);
      var a = safeApi();
      if(a) a.subscribe(wid, provider);
      else { pendingSubs.push(provider); if(!flushTimer) flushTimer = setInterval(tryFlush, 200); }
    },
    _push: function(msg){
      var arr = onCbs[msg.provider] || [];
      for (var i = 0; i < arr.length; i++){ try { arr[i](msg.value); } catch(e) {} }
    },
    runAction: function(a, p){ var x=safeApi(); return x ? x.run_widget_action(wid, a, p || {}) : Promise.resolve(null); },
    setClickThrough: function(on){ var x=safeApi(); return x ? x.set_click_through(wid, !!on) : Promise.resolve(null); },
    getSettings: function(){ var x=safeApi(); return x ? x.get_settings() : Promise.resolve({}); },
    moveWindow: function(x, y){ var a=safeApi(); return a ? a.move_window(wid, x, y) : Promise.resolve(null); },
    savePosition: function(x, y){ var a=safeApi(); return a ? a.save_position(wid, x, y) : Promise.resolve(null); },
    getRect: function(){ var a=safeApi(); return a ? a.get_window_rect(wid) : Promise.resolve(null); },
    saveLayout: function(n){ var a=safeApi(); return a ? a.save_layout(n) : Promise.resolve(null); },
    applyLayout: function(n){ var a=safeApi(); return a ? a.apply_layout(n) : Promise.resolve(null); },
    listLayouts: function(){ var a=safeApi(); return a ? a.list_layouts() : Promise.resolve([]); },
    deleteLayout: function(n){ var a=safeApi(); return a ? a.delete_layout(n) : Promise.resolve(null); },
    closeSettings: function(){ var a=safeApi(); return a ? a.close_settings() : Promise.resolve(null); }
  };
  window.__PALM_ON__ = window.PALM._push;

  function nearestEdge(x, y, w, h){
    var s = window.screen;
    var L = s.availLeft, T = s.availTop, R = s.availLeft + s.availWidth, B = s.availTop + s.availHeight;
    var M = 16;
    if (Math.abs(x - L) < M) x = L;
    else if (Math.abs(x + w - R) < M) x = R - w;
    if (Math.abs(y - T) < M) y = T;
    else if (Math.abs(y + h - B) < M) y = B - h;
    return [x, y];
  }

  var ghost = document.createElement('div');
  ghost.className = 'palm-drag-handle';
  ghost.textContent = '⠿';
  document.body.appendChild(ghost);

  function bindDrag(el){
    if(!el) return;
    el.addEventListener('mousedown', function(e){
      if(document.body.classList.contains('locked')) return;
      e.preventDefault();
      api.get_window_rect(wid).then(function(rect){
        var ox = rect.x, oy = rect.y, sx = e.clientX, sy = e.clientY, nx = ox, ny = oy;
        function onMove(ev){ nx = ox + (ev.clientX - sx); ny = oy + (ev.clientY - sy); api.move_window(wid, nx, ny); }
        function onUp(){
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
          var snapped = nearestEdge(nx, ny, rect.width, rect.height);
          api.move_window(wid, snapped[0], snapped[1]);
          api.save_position(wid, snapped[0], snapped[1]);
        }
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });
    });
  }
  bindDrag(ghost);
  var handles = document.querySelectorAll('.drag-handle');
  for (var i = 0; i < handles.length; i++){ bindDrag(handles[i]); }
})();
"""

# 设置窗也复用同一套基座样式（含拖拽把手）并叠加现代玻璃控件风格。
SETTINGS_STYLE = BASE_STYLE + """
body { color:#e8eefc; padding:18px; width:384px; box-sizing:border-box;
  font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif; }
.panel { background:rgba(18,22,38,.62); backdrop-filter:blur(16px) saturate(140%); -webkit-backdrop-filter:blur(16px) saturate(140%);
  border:1px solid rgba(255,255,255,.18); border-radius:18px; padding:18px; max-height:88vh; overflow:auto;
  box-shadow:0 16px 50px -12px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.2); }
h3 { margin:0 0 14px; font-size:17px; font-weight:700; letter-spacing:.5px; }
.sect { margin:14px 0; padding:14px; border:1px solid rgba(255,255,255,.10); border-radius:14px; background:rgba(255,255,255,.04); }
.sect-title { font-size:11px; letter-spacing:1.5px; color:rgba(255,255,255,.55); margin-bottom:10px; text-transform:uppercase; }
.row { margin:10px 0 }
label { display:flex; align-items:center; gap:8px; font-size:13px; margin-bottom:8px; }
button { padding:7px 12px; border-radius:10px; border:0; background:#3b82f6; color:#fff; cursor:pointer; font-size:13px;
  transition:background .15s, transform .1s, box-shadow .15s; }
button:hover { background:#2f6fe0; box-shadow:0 4px 12px rgba(59,130,246,.4); }
button:active { transform:scale(.97); }
button.ghost { background:rgba(255,255,255,.12); }
button.ghost:hover { background:rgba(255,255,255,.22); }
button.danger { background:#ef4444; }
button.danger:hover { background:#dc2626; }
input[type=text], select { background:rgba(255,255,255,.08); color:#e8eefc;
  border:1px solid rgba(255,255,255,.18); border-radius:8px; padding:6px 8px; font-size:13px; }
input[type=range]{ -webkit-appearance:none; appearance:none; height:4px; border-radius:999px;
  background:rgba(255,255,255,.2); outline:none; }
input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:14px; height:14px; border-radius:50%;
  background:#7dd3fc; cursor:pointer; box-shadow:0 0 6px rgba(125,211,252,.6); }
input[type=range]::-moz-range-thumb{ width:14px; height:14px; border:0; border-radius:50%; background:#7dd3fc; cursor:pointer; }
input[type=checkbox]{ width:16px; height:16px; accent-color:#7dd3fc; cursor:pointer; }
hr { border:0; border-top:1px solid rgba(255,255,255,.12); margin:14px 0 }
table { width:100%; border-collapse:collapse; font-size:12px; }
td, th { text-align:left; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.08); }
.muted { opacity:.7; font-size:12px }
.wcard { border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:10px; margin:8px 0; background:rgba(255,255,255,.03); }
.wcard .name { font-size:13px; font-weight:600; margin-bottom:8px; }
.wctrl { display:flex; flex-wrap:wrap; gap:10px 14px; align-items:center; font-size:12px; }
"""


def inject_shim(widget_id):
    """返回带具体 widget_id 的桥脚本。"""
    return SHIM_TEMPLATE.replace("__WIDGET_ID__", widget_id)
