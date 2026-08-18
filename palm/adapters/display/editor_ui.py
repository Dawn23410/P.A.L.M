"""组件编辑器 UI：用基座样式 + 原生桥装配编辑器界面。

功能：组件列表 → 选择后加载源码 → 编辑（HTML/CSS/JS 三栏，或 .html 单栏）
→ 保存即写回文件并经宿主 reload_widget 热重载（不重启整个程序）。

编辑器为纯内置实现（行号 + Tab 缩进 + Ctrl+S），不依赖任何外部 CDN，
离线/内网均可靠可用。
"""

from .injector import inject_shim, SETTINGS_STYLE


def build_editor_html():
    """返回编辑器窗口完整 HTML（无外部依赖）。"""
    shim = inject_shim("__editor__")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + SETTINGS_STYLE
        + EDITOR_STYLE
        + "</style></head><body>"
        "<div class='panel'>"
        "<div class='titlebar drag-handle'>P.A.L.M 组件编辑器（内置离线）</div>"
        "<div class='toolbar'>"
        "<select id='sel' style='width:200px'></select>"
        "<button id='save' class='primary'>保存并热重载</button>"
        "<span id='status' class='muted' style='margin-left:auto'></span>"
        "</div>"
        "<div id='tabs' class='tabs'>"
        "<button data-pane='html' class='tab active'>HTML</button>"
        "<button data-pane='css' class='tab'>CSS</button>"
        "<button data-pane='js' class='tab'>JS</button>"
        "</div>"
        "<div id='codeView'>"
        + _code_pane("html") + _code_pane("css") + _code_pane("js")
        + "</div>"
        + _raw_pane()
        + "</div>"
        "<script>" + shim + EDITOR_JS + "</script>"
        "</body></html>"
    )


def _code_pane(pane):
    cap = pane.upper()
    return (
        f"<div class='pane' data-pane='{pane}'>"
        f"<div class='codewrap'><pre class='gutter' id='g{cap}'>1</pre>"
        f"<textarea id='ed{cap}' class='ed' spellcheck='false'></textarea></div></div>"
    )


def _raw_pane():
    return (
        "<div id='rawView' style='display:none'>"
        "<div class='codewrap'><pre class='gutter' id='gRaw'>1</pre>"
        "<textarea id='edRaw' class='ed' spellcheck='false'></textarea></div></div>"
    )


EDITOR_STYLE = """
.titlebar { font-size:14px; font-weight:600; margin-bottom:8px; padding:4px 8px;
  background:rgba(255,255,255,.08); border-radius:8px; cursor:move; user-select:none; }
.toolbar { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.tabs { display:flex; gap:4px; margin-bottom:6px; }
.tab { background:rgba(255,255,255,.1); border:0; color:#e8eefc; padding:4px 12px;
  border-radius:6px; cursor:pointer; font-size:13px; }
.tab.active { background:#3b82f6; }
.pane { display:none; }
.pane.active { display:block; }
.codewrap { display:flex; height:440px; }
.gutter { margin:0; padding:10px 8px; box-sizing:border-box; width:42px; height:100%;
  overflow:hidden; text-align:right; background:rgba(0,0,0,.25); color:rgba(255,255,255,.4);
  border:1px solid rgba(255,255,255,.2); border-right:0; border-radius:8px 0 0 8px;
  font-family:"Cascadia Code","Consolas",monospace; font-size:13px; line-height:1.5;
  white-space:pre; user-select:none; }
.ed { flex:1; height:100%; box-sizing:border-box; resize:none; background:rgba(0,0,0,.35);
  color:#e8eefc; border:1px solid rgba(255,255,255,.2); border-radius:0 8px 8px 0;
  padding:10px; font-family:"Cascadia Code","Consolas",monospace; font-size:13px; line-height:1.5; }
button.primary { background:#3b82f6; }
"""


EDITOR_JS = """
var api = window.pywebview.api;
var currentId = null, currentType = 'pwidget';

function setStatus(msg){ document.getElementById('status').textContent = msg; }
function taOf(pane){ return document.getElementById('ed' + (pane === 'raw' ? 'Raw' : pane[0].toUpperCase() + pane.slice(1))); }
function gutterOf(pane){ return document.getElementById('g' + (pane === 'raw' ? 'Raw' : pane[0].toUpperCase() + pane.slice(1))); }

// ---------- 行号 + Tab 缩进 ----------
function syncGutter(pane){
  var ta = taOf(pane); if (!ta) return;
  var lines = ta.value.split('\\n').length || 1;
  var g = gutterOf(pane);
  var out = '';
  for (var i = 1; i <= lines; i++){ out += i + '\\n'; }
  g.textContent = out;
  g.scrollTop = ta.scrollTop;
}
function bindEditor(pane){
  var ta = taOf(pane); if (!ta) return;
  ta.addEventListener('input', function(){ syncGutter(pane); });
  ta.addEventListener('scroll', function(){ gutterOf(pane).scrollTop = ta.scrollTop; });
  ta.addEventListener('keydown', function(e){
    if (e.key === 'Tab'){
      e.preventDefault();
      var s = ta.selectionStart, en = ta.selectionEnd;
      ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(en);
      ta.selectionStart = ta.selectionEnd = s + 2;
      syncGutter(pane);
    }
  });
}
['html','css','js','raw'].forEach(bindEditor);

// ---------- 组件列表 ----------
function refreshList(){
  api.list_widgets().then(function(ws){
    var sel = document.getElementById('sel'); sel.innerHTML = '';
    if (!ws.length){ sel.innerHTML = '<option>无组件</option>'; setStatus('没有可编辑的组件'); return; }
    ws.forEach(function(w){ var o = document.createElement('option'); o.value = w.id; o.textContent = w.name + ' (' + w.id + ')'; sel.appendChild(o); });
    loadWidget(sel.value);
  }).catch(function(e){ setStatus('加载列表失败：' + e); });
}

function loadWidget(id){
  if (!id) return;
  currentId = id;
  api.get_widget_source(id).then(function(src){
    if (src.error){ setStatus('读取源码失败：' + src.error); return; }
    currentType = src.type;
    if (src.type === 'html'){
      document.getElementById('codeView').style.display = 'none';
      document.getElementById('tabs').style.display = 'none';
      document.getElementById('rawView').style.display = 'block';
      document.getElementById('edRaw').value = src.raw || '';
      syncGutter('raw');
    } else {
      document.getElementById('codeView').style.display = 'block';
      document.getElementById('tabs').style.display = 'flex';
      document.getElementById('rawView').style.display = 'none';
      document.getElementById('edHtml').value = src.html || '';
      document.getElementById('edCss').value = src.css || '';
      document.getElementById('edJs').value = src.js || '';
      syncGutter('html'); syncGutter('css'); syncGutter('js');
    }
    setStatus('已载入：' + id);
  }).catch(function(e){ setStatus('读取源码失败：' + e); });
}

// ---------- 标签切换 ----------
document.querySelectorAll('.tab').forEach(function(btn){
  btn.onclick = function(){
    document.querySelectorAll('.tab').forEach(function(b){ b.classList.remove('active'); });
    document.querySelectorAll('.pane').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    document.querySelector('.pane[data-pane="' + btn.dataset.pane + '"]').classList.add('active');
  };
});

// ---------- 保存（热重载） ----------
function collectSource(){
  if (currentType === 'html'){
    return { type:'html', raw: document.getElementById('edRaw').value };
  }
  return {
    type: currentType,
    html: document.getElementById('edHtml').value,
    css: document.getElementById('edCss').value,
    js: document.getElementById('edJs').value
  };
}

function doSave(){
  if (!currentId){ setStatus('请先选择组件'); return; }
  var src = collectSource();
  setStatus('保存中…');
  api.save_widget_source(currentId, src).then(function(r){
    if (r && r.error){ setStatus('保存失败：' + r.error); }
    else { setStatus('已热重载：' + currentId + '（无需重启）'); }
  }).catch(function(e){ setStatus('保存失败：' + e); });
}

document.getElementById('save').onclick = doSave;
document.getElementById('sel').onchange = function(){ loadWidget(this.value); };
document.addEventListener('keydown', function(e){
  if (e.ctrlKey && (e.key === 's' || e.key === 'S')){ e.preventDefault(); doSave(); }
});

refreshList();
"""
