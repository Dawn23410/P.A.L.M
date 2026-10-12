/**
 * 「添加模型」弹窗（独立模块）
 * ==========================
 * 从 设置→聊天→模型设置 的「添加模型」按钮打开。上层窗口：
 * 全屏半透明蒙版 + 居中偏上面板；Esc / 点蒙版 / 取消 均可关闭。
 *
 * 「获取模型列表」走 LLM 内核后端 POST /api/models/discover：
 * 协议差异（OpenAI 兼容 / Anthropic / Gemini / Ollama 原生）由后端 discovery 层消化，
 * 失败时后端返回 502 + 可读文案（401 鉴权失败 / 404 路径不对 / 网络不可达），原样回显。
 *
 * 模型卡片 = 模型名称 + 供应商 + 功能标签（多色，调研快照推断）+ 添加模型按钮
 * （已添加 → 灰色「已添加」）。点卡片选中后可在下方勾选区微调功能，再点卡片按钮落库。
 * 功能推断依据 2026-09 调研：供应商级默认能力 + 模型名模式匹配，仅作预填建议。
 */

const STYLE_ID = 'model-modal-style';
/* 模型清单已经在页面的「模型设置」里统一读写内核配置（kernel-api），
   本弹窗不再自己碰存储，也不再自己拼后端地址。 */

import {
  VENDORS, GROUPS, PROTOCOLS, FEAT_META, THINK_LEVELS, resolveFeatures, ollamaHint, tagsHtml,
} from './vendor-data.js';
import { getMeta, setMeta, formatCtx } from './model-meta.js';
import { discoverModels, discoverOllamaInfo } from './kernel-api.js';

const CSS = `
.mm-mask{
  position:fixed;inset:0;z-index:1000;
  background:rgba(0,0,0,.42);              /* 四边蒙版半透明 */
  display:flex;align-items:flex-start;justify-content:center;
  overflow:auto;padding:16px;
}
.mm-panel{
  margin-top:9vh;                          /* 中央偏上 */
  width:560px;max-width:100%;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  border:1px solid var(--ui-border,#e0e0e0);border-radius:12px;
  box-shadow:0 18px 50px rgba(0,0,0,.22);
  padding:18px 20px 16px;
  font-size:0.9286rem;
  display:flex;flex-direction:column;gap:14px;
}
.mm-title{font-size:1.0714rem;font-weight:700;}

.mm-form{display:flex;flex-direction:column;gap:12px;}
.mm-row{display:flex;align-items:center;gap:10px;}
.mm-row>label{flex:none;width:76px;font-size:0.8571rem;color:var(--ui-muted,#6b6b6b);}
.mm-row>input,.mm-row>select{
  flex:1 1 auto;min-width:0;height:30px;padding:0 10px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;
}
.mm-row>input:focus,.mm-row>select:focus{
  outline:none;border-color:var(--ui-accent,#0969da);
  box-shadow:0 0 0 2px color-mix(in srgb,var(--ui-accent,#0969da) 18%,transparent);
}
.mm-row>input:disabled,.mm-row>select:disabled{
  background:var(--ui-panel,#f5f5f5);color:var(--ui-faint,#9a9a9a);
  cursor:not-allowed;box-shadow:none;
}
.mm-row>input::placeholder{color:var(--ui-faint,#9a9a9a);}

/* 上下文长度选择框 + 自定义数值输入 */
.mm-ctxnum{
  flex:0 0 130px;min-width:0;height:30px;padding:0 10px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;
}
.mm-ctxnum[hidden]{display:none;}
.mm-ctxhint{flex:none;font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);}

.mm-fetch{
  flex:none;height:30px;padding:0 14px;
  border:1px solid var(--ui-border,#e0e0e0);border-radius:7px;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.8571rem;cursor:pointer;
  transition:background .16s;
}
.mm-fetch:hover:not(:disabled){background:var(--ui-hover);}
.mm-fetch:disabled{opacity:.55;cursor:wait;}

.mm-err{
  display:none;padding:8px 12px;border-radius:8px;
  border:1px solid color-mix(in srgb,var(--ui-danger,#d1242f) 35%,transparent);
  background:color-mix(in srgb,var(--ui-danger,#d1242f) 8%,transparent);
  color:var(--ui-danger,#d1242f);
  font-size:0.8571rem;line-height:1.5;white-space:pre-wrap;word-break:break-word;
}
.mm-err.on{display:block;}

.mm-list{
  display:none;flex-direction:column;gap:8px;
  max-height:220px;overflow-y:auto;padding:2px;
  scrollbar-width:none;-ms-overflow-style:none;  /* 滚动保留、滚动条隐藏 */
}
.mm-list::-webkit-scrollbar{display:none;width:0;height:0;}
.mm-list.on{display:flex;}
.mm-mcard{
  border:1px solid var(--ui-border,#e0e0e0);border-radius:9px;
  background:var(--ui-elev,#fff);cursor:pointer;
  padding:8px 12px;text-align:left;font-family:inherit;
  /* 扁平式水平排列：名称 / 供应商·协议 / 功能标签 / 按钮 全部收在一行 */
  display:flex;align-items:center;gap:12px;
  transition:border-color .16s,box-shadow .16s;
}
.mm-mcard:hover{background:var(--ui-hover);}
.mm-mcard.on{
  border-color:var(--ui-accent,#0969da);
  box-shadow:0 0 0 2px color-mix(in srgb,var(--ui-accent,#0969da) 22%,transparent);
}
.mm-cmain{flex:1 1 auto;min-width:0;display:flex;align-items:center;flex-wrap:wrap;gap:4px 10px;}
.mm-mcard .n{flex:0 1 auto;min-width:0;font-weight:600;font-size:0.9286rem;word-break:break-all;}
.mm-cmeta{flex:none;font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);}
/* ollama 专属版本提示（去审查版 / 指令版 / 视觉版 …） */
.mm-ver{
  flex:none;display:inline-block;padding:0 7px;border-radius:999px;
  font-size:0.7143rem;line-height:1.6;white-space:nowrap;
  background:#eaf7ee;color:#1a7f37;border:1px solid #bfe6cc;
}

/* 卡片「添加模型」按钮：已添加 → 灰色禁用 */
.mm-addbtn{
  flex:none;height:26px;padding:0 12px;min-width:76px;
  border:1px solid var(--ui-accent,#0969da);border-radius:7px;
  background:var(--ui-accent,#0969da);color:#fff;
  font-family:inherit;font-size:0.7857rem;cursor:pointer;
  transition:opacity .16s,background .16s;
}
.mm-addbtn:hover:not(:disabled){opacity:.88;}
.mm-addbtn:disabled{
  background:var(--ui-panel,#f5f5f5);color:var(--ui-faint,#9a9a9a);
  border-color:var(--ui-border,#e0e0e0);cursor:not-allowed;
}

/* 功能标签：多色 pill */
.mm-tags{display:flex;flex-wrap:wrap;gap:6px;}
.mm-tags:empty{display:none;}
.mm-tag{
  display:inline-block;padding:1px 8px;border-radius:999px;
  font-size:0.7143rem;line-height:1.6;white-space:nowrap;
}
.mm-tag.f-reason{background:#f3e8ff;color:#8250df;}   /* 深度思考：紫 */
.mm-tag.f-levels{background:#dff5f2;color:#0f7f72;}   /* 多思考深度：青 */
.mm-tag.f-ctx{background:#eef0f3;color:#5b6572;}      /* 上下文长度：灰 */
.mm-tag.f-tools{background:#e3effc;color:#0969da;}    /* 工具调用：蓝 */
.mm-tag.f-files{background:#ffeed9;color:#b45e04;}    /* 文件读取：橙 */
.mm-tag.f-vision{background:#ffe3ec;color:#c22758;}   /* 图片查看：玫红 */

.mm-feats{display:flex;flex-direction:column;gap:8px;}
/* 功能支持：四项平行横排一行（而非原来每项一行竖排） */
.mm-featrow{display:flex;flex-wrap:wrap;gap:6px 18px;padding:2px 0;}
.mm-feat{
  /* 勾选框紧跟在文字之后，不再左右分居两端 */
  flex:none;display:flex;align-items:center;justify-content:flex-start;gap:8px;
  padding:2px 0;cursor:pointer;font-size:0.9286rem;
}
.mm-feat input,.mm-lv input{
  width:16px;height:16px;flex:none;margin:0;cursor:pointer;
  accent-color:var(--ui-accent,#0969da);
}
/* 勾选框在文字之后时，标签文字不该被拉满整行 */
.mm-feat > span:first-child{ flex:none; }
.mm-feat>span:first-child,.mm-lv>span:first-child{color:var(--ui-text,#1a1a1a);}
.mm-lvgroup{
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  padding:2px 0;
}
.mm-lv{
  display:flex;align-items:center;gap:6px;cursor:pointer;
  font-size:0.9286rem;color:var(--ui-text,#1a1a1a);
}
.mm-sublabel{
  font-size:0.8571rem;color:var(--ui-muted,#6b6b6b);
  width:76px;flex:none;
}
.mm-feathint{font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);}

.mm-foot{display:flex;justify-content:flex-end;gap:10px;margin-top:2px;}
.mm-btn{
  height:32px;padding:0 18px;border-radius:8px;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  font-family:inherit;font-size:0.9286rem;transition:background .16s;
}
.mm-btn:hover{background:var(--ui-hover);}
`;

function injectStyle() {
  const old = document.getElementById(STYLE_ID);
  if (old) old.remove();
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = CSS;
  document.head.appendChild(el);
}

/** 拉取模型列表：返回模型 id 数组；失败抛 Error(message)（message 已是人话文案）
 *  统一走 kernel-api，不再自己 fetch —— 否则错误文案与出口都不一致。 */
async function fetchModels(type, base, key) {
  return discoverModels(type, base, key);
}

/**
 * 打开弹窗。
 * @param {{ onAdd: (model: object) => void }} opts 添加完成回调
 * @returns {{ close: () => void }}
 */
export function openModelModal(opts) {
  injectStyle();

  const groupOptions = (gk) => Object.entries(VENDORS)
    .filter(([, v]) => v.group === gk)
    .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('');

  const mask = document.createElement('div');
  mask.className = 'mm-mask';
  mask.innerHTML = `
    <div class="mm-panel" role="dialog" aria-label="添加模型">
      <div class="mm-title">添加模型</div>
      <div class="mm-form">
        <div class="mm-row">
          <label>模型供应商</label>
          <select data-vendor>
            ${GROUPS.map((g) => `<optgroup label="${g.label}">${groupOptions(g.key)}</optgroup>`).join('')}
          </select>
        </div>
        <div class="mm-row">
          <label>协议</label>
          <select data-type>
            ${PROTOCOLS.map((p) => `<option value="${p.key}">${p.label}</option>`).join('')}
          </select>
        </div>
        <div class="mm-row">
          <label>请求地址</label>
          <input data-base type="text" placeholder="如 https://api.example.com/v1" />
        </div>
        <div class="mm-row">
          <label>API Key</label>
          <input data-key type="password" placeholder="必填" autocomplete="off" />
        </div>
        <div class="mm-row">
          <label>上下文长度</label>
          <select data-ctx>
            <option value="">不填写</option>
            <option value="4096">4K</option>
            <option value="8192">8K</option>
            <option value="16384">16K</option>
            <option value="32768">32K</option>
            <option value="65536">64K</option>
            <option value="131072">128K</option>
            <option value="262144">256K</option>
            <option value="524288">512K</option>
            <option value="1048576">1M</option>
            <option value="__custom">自定义…</option>
          </select>
          <input class="mm-ctxnum" data-ctxnum type="number" min="1" step="1000"
                 placeholder="如 200000" hidden />
          <span class="mm-ctxhint" data-ctxhint></span>
        </div>
        <div class="mm-row">
          <label></label>
          <button class="mm-fetch" type="button" data-fetch>获取模型列表</button>
        </div>
      </div>
      <div class="mm-err" data-err></div>
      <div class="mm-list" data-list></div>
      <div class="mm-feats">
        <div class="mm-row"><span class="mm-sublabel">功能支持</span><span class="mm-feathint">选中模型后按模型信息自动预填，可手动微调</span></div>
        <div class="mm-featrow">
          ${FEAT_META.filter((f) => f.key !== 'levels').map((f) => `
          <label class="mm-feat">
            <span>${f.label}</span>
            <input type="checkbox" data-feat="${f.key}" />
          </label>`).join('')}
        </div>
        <div class="mm-row" style="margin-top:6px;">
          <span class="mm-sublabel">思考强度</span>
          <span class="mm-feathint">该模型支持哪些档位就勾哪些，可多选</span>
        </div>
        <div class="mm-lvgroup" data-lvgroup>
          ${THINK_LEVELS.map((lv) => `
            <label class="mm-lv" title="${lv.hint}">
              <input type="checkbox" data-lv="${lv.key}" />
              <span>${lv.label}</span>
            </label>`).join('')}
        </div>
      </div>
      <div class="mm-foot">
        <button class="mm-btn" type="button" data-cancel>取消</button>
      </div>
    </div>`;

  const panel = mask.querySelector('.mm-panel');
  const vendorSel = mask.querySelector('[data-vendor]');
  const typeSel = mask.querySelector('[data-type]');
  const baseInp = mask.querySelector('[data-base]');
  const keyInp = mask.querySelector('[data-key]');
  const fetchBtn = mask.querySelector('[data-fetch]');
  const errBox = mask.querySelector('[data-err]');
  const listBox = mask.querySelector('[data-list]');
  const ctxSel = mask.querySelector('[data-ctx]');
  const ctxNum = mask.querySelector('[data-ctxnum]');
  const ctxHint = mask.querySelector('[data-ctxhint]');

  let picked = '';            // 当前选中的模型 id
  let fetching = false;
  let currentModels = [];     // 最近一次获取到的模型 id 列表
  let currentInfo = {};       // ollama：最近一次获取到的模型详情（name -> {ctx,capabilities,...}）

  const syncVendor = () => {
    const v = VENDORS[vendorSel.value];
    const custom = vendorSel.value === 'custom';
    typeSel.value = v.type;
    baseInp.value = v.base;
    typeSel.disabled = !custom;      // 预设供应商：协议/地址整套跟随预设
    baseInp.disabled = !custom;
    syncKeyState();
  };

  const syncKeyState = () => {
    const noKey = typeSel.value === 'ollama';   // Ollama 本地服务无需 Key
    keyInp.disabled = noKey;
    keyInp.placeholder = noKey ? 'Ollama 无需 API Key' : '必填';
    if (noKey) keyInp.value = '';
  };

  /* ── 上下文长度选择框 ──
   * 预置常见档位；发现到模型自带 ctx 时自动选中，档位表里没有的值临时插一条。 */
  const CTX_PRESET_VALUES = Array.from(ctxSel.options)
    .map((o) => o.value)
    .filter((v) => v && v !== '__custom');

  const isCustomCtx = () => ctxSel.value === '__custom';

  const syncCtxCustom = () => {
    const custom = isCustomCtx();
    ctxNum.hidden = !custom;
    if (custom) ctxNum.focus();
  };

  /** 把数字写进选择框：命中预置就选中，否则插一条临时选项
   *  @param {number|null} n 上下文长度
   *  @param {string} [note] 右侧说明文案（缺省「来自模型信息」） */
  const setCtxValue = (n, note) => {
    const v = Number(n);
    const has = Number.isFinite(v) && v > 0;
    Array.from(ctxSel.options).forEach((o) => { if (o.dataset.temp) o.remove(); });
    ctxNum.value = '';
    if (!has) { ctxSel.value = ''; ctxHint.textContent = ''; syncCtxCustom(); return; }
    const s = String(Math.floor(v));
    if (CTX_PRESET_VALUES.indexOf(s) >= 0) {
      ctxSel.value = s;
    } else {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = formatCtx(v) + '（' + s + '）';
      opt.dataset.temp = '1';
      ctxSel.insertBefore(opt, ctxSel.querySelector('option[value="__custom"]'));
      ctxSel.value = s;
    }
    ctxHint.textContent = note || '来自模型信息';
    syncCtxCustom();
  };

  /** 读出用户最终选定的上下文长度；空 = 不填写 */
  const readCtx = () => {
    const raw = isCustomCtx() ? ctxNum.value.trim() : ctxSel.value;
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
  };

  /* ollama 实时信息：优先用刚发现到的，其次回落已落盘的记录（模型信息记录） */
  const liveFor = (id) => {
    const l = currentInfo[id];
    if (l) return l;
    const m = getMeta(vendorSel.value, id);
    if (m.caps.length || Object.keys(m.info).length || m.ctx) {
      return {
        ctx: m.ctx, capabilities: m.caps,
        ctxMax: m.info.ctxMax,
        parameterSize: m.info.parameterSize,
        quantization: m.info.quantization,
        family: m.info.family,
      };
    }
    return null;
  };

  const showError = (msg) => {
    errBox.textContent = msg;
    errBox.classList.add('on');
  };
  const clearError = () => {
    errBox.textContent = '';
    errBox.classList.remove('on');
  };

  /* 「已添加」的判定必须来自内核配置（模型现在存在 config.json 的
     providers[].models 里）。此前这里读的是 localStorage['webui.models']，
     而那个键在配置统一时已被迁移删除 —— 导致任何模型都不会显示「已添加」。
     现由调用方通过 opts.isAdded 注入判定函数。 */
  const isAdded = (model) => {
    if (typeof opts.isAdded === 'function') {
      try { return !!opts.isAdded(vendorSel.value, model); } catch (e) { return false; }
    }
    return false;
  };

  /* 功能标签统一走 vendor-data.js 的 tagsHtml（它会把思考挡位渲染成
     「思考 低/中/高」）。这里原本又定义了一个同名函数，把导入遮蔽成了死代码，
     挡位信息因此一直渲染不出来。 */

  /** HTML 转义。模型 id 来自上游 /api/models/discover，是不可信数据；
   *  直接拼进 innerHTML 会导致属性逃逸与标签注入（实测 <img src=x onerror>
   *  会真的执行），所以凡是拼进 HTML 的动态值都要过这里。 */
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  /** 勾选区 ↔ 推断值联动：功能位与思考挡位一起预填 */
  const setFeatEditor = (features) => {
    const f = features || {};
    mask.querySelectorAll('input[data-feat]').forEach((b) => {
      b.checked = !!f[b.dataset.feat];
    });
    const lv = Array.isArray(f.thinkLevels) ? f.thinkLevels : [];
    mask.querySelectorAll('input[data-lv]').forEach((b) => {
      b.checked = lv.indexOf(b.dataset.lv) >= 0;
    });
  };
  const collectFeatures = () => {
    const out = {};
    mask.querySelectorAll('input[data-feat]').forEach((b) => { out[b.dataset.feat] = b.checked; });
    const lv = Array.from(mask.querySelectorAll('input[data-lv]'))
      .filter((b) => b.checked)
      .map((b) => b.dataset.lv);
    out.thinkLevels = lv;          // 具体挡位：低 / 中 / 高
    out.levels = lv.length > 0;    // 派生：有任一挡位即视为支持多思考深度
    return out;
  };

  const renderList = () => {
    picked = '';
    const vendor = vendorSel.value;
    const v = VENDORS[vendor];
    const pLabel = PROTOCOLS.find((p) => p.key === typeSel.value)?.label || typeSel.value;
    const base = baseInp.value.trim();
    listBox.innerHTML = currentModels.map((id) => {
      const added = isAdded(id);
      const live = liveFor(id);
      // 功能位：ollama 走本地记录，其余走内核档案（统一入口，三处渲染口径一致）
      const feats = resolveFeatures(vendor, id, base, live);
      const safeId = esc(id);
      const m = getMeta(vendor, id);
      // 上下文：生效上限优先（ollama 的 num_ctx），其次前端附加属性
      const ctxN = (live && Number(live.ctx) > 0) ? Number(live.ctx) : m.ctx;
      const ctxMax = live && Number(live.ctxMax) > 0 ? Number(live.ctxMax) : 0;
      const ctxTitle = (ctxMax && ctxN && ctxMax > ctxN)
        ? ('已设上下文 ' + formatCtx(ctxN) + '（模型架构上限 ' + formatCtx(ctxMax) + '）')
        : '上下文长度';
      const ctxTag = ctxN
        ? '<span class="mm-tag f-ctx" title="' + esc(ctxTitle) + '">' + esc(formatCtx(ctxN)) + ' 上下文</span>'
        : '';
      // ollama 专属版本提示（去审查版 / 指令版 / 视觉版 …）
      const ver = ollamaHint(vendor, id, live);
      const verTag = ver
        ? '<span class="mm-ver" title="ollama 模型版本形态">' + esc(ver) + '</span>'
        : '';
      return `
      <div class="mm-mcard" data-model="${safeId}">
        <div class="mm-cmain">
          <span class="n">${safeId}</span>
          ${verTag}
          <span class="mm-cmeta">${esc(v.short || v.label)} · ${esc(pLabel)}</span>
          <span class="mm-tags">${tagsHtml(feats, 'mm-tag')}${ctxTag}</span>
        </div>
        <button class="mm-addbtn" type="button" data-addmodel ${added ? 'disabled' : ''}>${added ? '已添加' : '添加模型'}</button>
      </div>`;
    }).join('');
    listBox.classList.add('on');
  };

  const selectCard = (card) => {
    listBox.querySelectorAll('.mm-mcard').forEach((c) => c.classList.toggle('on', c === card));
    picked = card.dataset.model;
    const vendor = vendorSel.value;
    const live = liveFor(picked);
    // 底部勾选区跟随选中卡片：按该模型的「模型信息记录」自动预填（可再微调）
    setFeatEditor(resolveFeatures(vendor, picked, baseInp.value.trim(), live));
    // 上下文长度选择框同步该模型的值（生效上限优先，无记录则清空）
    const m = getMeta(vendor, picked);
    const ctxN = (live && Number(live.ctx) > 0) ? Number(live.ctx) : m.ctx;
    const ctxMax = live && Number(live.ctxMax) > 0 ? Number(live.ctxMax) : 0;
    const note = (ctxMax && ctxN && ctxMax > ctxN)
      ? ('来自模型信息 · 架构上限 ' + formatCtx(ctxMax))
      : '来自模型信息';
    setCtxValue(ctxN, note);
  };

  const onListClick = (e) => {
    const addBtn = e.target.closest('[data-addmodel]');
    const card = e.target.closest('.mm-mcard');
    if (!card) return;
    if (addBtn) {
      if (addBtn.disabled) return;
      if (picked !== card.dataset.model) selectCard(card);   // 落库前以勾选区当前值为准
      addToStore(card.dataset.model);
      return;
    }
    selectCard(card);
  };

  const addToStore = (model) => {
    const v = VENDORS[vendorSel.value];
    const p = PROTOCOLS.find((x) => x.key === typeSel.value);
    (opts.onAdd || (() => {}))({
      id: 'mm_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6),
      model,
      vendor: vendorSel.value,
      vendorLabel: v.short || v.label,
      type: typeSel.value,
      typeLabel: p ? p.label : typeSel.value,
      base: baseInp.value.trim(),
      key: keyInp.value.trim(),
      features: collectFeatures(),
      ctx: readCtx(),
    });
    // 就地更新该卡片按钮为「已添加」，不重拉列表
    // （注：模块顶部的 const CSS 是样式字符串，遮蔽了原生 CSS API，这里不能用 CSS.escape）
    const card = [...listBox.querySelectorAll('.mm-mcard')].find((c) => c.dataset.model === model);
    if (card) {
      const btn = card.querySelector('[data-addmodel]');
      btn.disabled = true;
      btn.textContent = '已添加';
    }
  };

  const close = () => {
    document.removeEventListener('keydown', onKey, true);
    mask.remove();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
  };

  const onFetch = async () => {
    if (fetching) return;
    clearError();
    const base = baseInp.value.trim();
    if (!base) { showError('请先填写请求地址。'); return; }
    const key = keyInp.value.trim();
    if (typeSel.value !== 'ollama' && !key) { showError('请先填写 API Key。'); return; }
    fetching = true;
    fetchBtn.disabled = true;
    fetchBtn.textContent = '获取中…';
    try {
      currentModels = await fetchModels(typeSel.value, base, key);
      if (typeSel.value === 'ollama') {
        // 获取模型列表的同时，也拿到每个模型的信息（上下文长度 / 能力 / 参数量 / 量化）
        try {
          currentInfo = await discoverOllamaInfo(base);
        } catch (e2) {
          currentInfo = {};
          showError('模型列表已获取，但读取模型详情失败：' + (e2 && e2.message ? e2.message : e2));
        }
        // 按模型落盘（模型信息记录）：设置页卡片、下次打开弹窗都能直接用
        currentModels.forEach((id) => {
          const l = currentInfo[id];
          if (!l) return;
          const patch = {
            caps: l.capabilities,
            info: {
              family: l.family, parameterSize: l.parameterSize,
              quantization: l.quantization, ctxMax: l.ctxMax,
            },
          };
          // ctx 存「生效上限」：Modelfile 的 num_ctx 优先，没有才用架构上限
          if (Number(l.ctx) > 0) patch.ctx = Number(l.ctx);
          setMeta('ollama', id, patch);
        });
      } else {
        currentInfo = {};
      }
      renderList();
    } catch (e) {
      currentModels = [];
      currentInfo = {};
      listBox.classList.remove('on');
      listBox.innerHTML = '';
      showError(e.message);
    } finally {
      fetching = false;
      fetchBtn.disabled = false;
      fetchBtn.textContent = '获取模型列表';
    }
  };

  vendorSel.addEventListener('change', () => {
    syncVendor();
    // 切供应商即作废旧列表：模型清单属于原上游，换个标签重渲染只会误导
    currentModels = [];
    currentInfo = {};
    listBox.classList.remove('on');
    listBox.innerHTML = '';
    clearError();
    // 换供应商后模型清单作废，功能区也回到该供应商的默认值，
    // 免得留着上一家模型的能力让人误以为已经推断过了
    setFeatEditor(resolveFeatures(vendorSel.value, '', '', null));
    setCtxValue(null);
  });
  typeSel.addEventListener('change', () => { syncKeyState(); });
  ctxSel.addEventListener('change', syncCtxCustom);
  fetchBtn.addEventListener('click', onFetch);
  listBox.addEventListener('click', onListClick);
  mask.querySelector('[data-cancel]').addEventListener('click', close);
  mask.addEventListener('mousedown', (e) => { if (!panel.contains(e.target)) close(); });  // 点蒙版关闭
  document.addEventListener('keydown', onKey, true);

  document.body.appendChild(mask);
  syncVendor();
  syncCtxCustom();
  setFeatEditor(resolveFeatures(vendorSel.value, '', '', null));
  return { close };
}
