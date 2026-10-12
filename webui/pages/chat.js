/**
 * 聊天模块
 * ========
 * HTML 主导的对话界面：消息列表 + 输入区。
 *
 * 生命周期：mount(host) -> { onShow, onHide, destroy }
 *
 * 设计说明：
 *   - 纯前端，暂无后端；发送后先本地回显，再用一个「占位回复」把
 *     交互闭环跑通（接后端时只需替换 _reply() 的实现）。
 *   - 消息内容全部走 textContent 写入，不用 innerHTML —— 用户输入
 *     直接进 DOM 有 XSS 风险，这里从根上避免。
 *   - 配色统一用全局主题变量 --ui-*，亮暗自动跟随（见 core/theme）。
 */

import { log } from '../core/log.js';
import { KERNEL_BASE, getConfig } from './kernel-api.js';
import { resolveFeatures } from './vendor-data.js';
import { getMeta } from './model-meta.js';

const STYLE_ID = 'mod-chat-style';

const CSS = `
.mod-chat{
  height:100%;display:flex;flex-direction:column;
  background:var(--ui-bg,#fff);color:var(--ui-text,#1a1a1a);
  /* 消息区左右边距 */
  --c-gutter:28px;
  /* 输入框左右边距：刻意比消息区小 —— 输入框要「贴到两侧」，只留一点点间隔 */
  --c-gutter-box:10px;
  transition:background .2s ease,color .2s ease;
}

/* ---------- 消息列表 ---------- */
.mod-chat .c-list{
  flex:1;min-height:0;overflow-y:auto;
  /* 必须是 flex 容器：空态 .c-empty{flex:1} 靠它才能撑满并垂直居中，
     否则 .c-empty 只是块级元素，会被顶到最上面。 */
  display:flex;flex-direction:column;
  padding:24px 0 8px;
}
.mod-chat .c-inner{
  /* 不再限宽：跟随主区域自适应，只留固定边距。
     与输入区共用 --c-gutter，保证两处严格同宽。 */
  margin:0 auto;padding:0 var(--c-gutter);
  display:flex;flex-direction:column;gap:18px;
  /* .c-list 现在是 flex 容器，显式禁止收缩，
     避免消息多时被 flex 压缩（空态的 flex:1 由 .c-empty 自己负责撑高） */
  flex:0 0 auto;
}

.mod-chat .c-row{display:flex;gap:10px;align-items:flex-start;padding:0 8px;}
.mod-chat .c-row.me{flex-direction:row-reverse;}

.mod-chat .c-avatar{
  flex:none;width:28px;height:28px;border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-size:0.7857rem;font-weight:600;user-select:none;
  background:var(--ui-hover);color:var(--ui-muted);
}
.mod-chat .c-row.me .c-avatar{
  background:var(--ui-accent-solid,#0969da);color:var(--ui-on-accent,#fff);
}

.mod-chat .c-body{
  min-width:0;display:flex;flex-direction:column;gap:4px;
  /* 不再用气泡卡片：内容直接铺开，宽度跟随容器但留可读上限 */
  max-width:min(92%, 820px);
}
.mod-chat .c-row.me .c-body{align-items:flex-end;}

.mod-chat .c-meta{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);padding:0 2px;
  display:flex;gap:6px;align-items:baseline;
}
.mod-chat .c-name{font-weight:600;color:var(--ui-muted,#6b6b6b);}
.mod-chat .c-time{font-variant-numeric:tabular-nums;}
/* 设置页关闭「显示消息时间」时，整页隐藏时间（含已有消息，无需重渲染） */
.mod-chat.no-time .c-time{display:none;}

/* 回合统计（Token 统计 + 详细信息），数据来自后端 done 事件的归一 stats */
.mod-chat .c-stats{
  margin-top:6px;display:flex;flex-direction:column;gap:2px;
  font-size:0.7857rem;line-height:1.5;color:var(--ui-faint,#9a9a9a);
  font-variant-numeric:tabular-nums;
}
.mod-chat .c-stats-detail{ word-break:break-all; }
.mod-chat.no-tok .c-stats-tok{display:none;}
.mod-chat.no-detail .c-stats-detail{display:none;}

/* 不再使用聊天气泡卡片：消息内容直接平铺显示，仅保留排版与主题色。
   显示区域比边界略小（.c-row 左右各留 8px 内缩），不贴边。 */
.mod-chat .c-bubble{
  font-size:0.9286rem;line-height:1.65;
  /* 同 .c-input：用 overflow-wrap:anywhere 而不是 word-break:break-word，
     否则回复里的长 URL / 长串也会整段挪行、撑破气泡 */
  white-space:pre-wrap;overflow-wrap:anywhere;
  background:transparent;border:none;border-radius:0;padding:0;
  color:var(--ui-text,#1a1a1a);
}
.mod-chat .c-row.me .c-bubble{
  color:var(--ui-text,#1a1a1a);
}
/* 用户消息的附件清单 */
.mod-chat .c-atts{
  font-size:0.7857rem;color:var(--ui-faint,#9a9a9a);
  word-break:break-all;text-align:right;
}

/* 助手回复直接以 Markdown 渲染到气泡 innerHTML 里 —— 气泡保留
   自身的外框 / 圆角 / 主题背景，下面这套专门约束内部 Markdown 排版，
   让它贴合聊天气泡的小字号 + 紧凑行高，不再出现"巨大卡片包几行字" */
.mod-chat .c-bubble > *{margin:.4em 0}
.mod-chat .c-bubble > *:first-child{margin-top:0}
.mod-chat .c-bubble > *:last-child{margin-bottom:0}
.mod-chat .c-bubble h1,
.mod-chat .c-bubble h2,
.mod-chat .c-bubble h3,
.mod-chat .c-bubble h4{
  font-size:1em;font-weight:600;margin:.55em 0 .25em;line-height:1.4;
}
.mod-chat .c-bubble p{margin:.35em 0;line-height:1.65}
.mod-chat .c-bubble strong{font-weight:600}
.mod-chat .c-bubble em{font-style:italic}
.mod-chat .c-bubble ul,
.mod-chat .c-bubble ol{margin:.35em 0;padding-left:1.4em}
.mod-chat .c-bubble li{margin:.12em 0}
.mod-chat .c-bubble li > p{margin:.12em 0}
.mod-chat .c-bubble code{
  background:var(--ui-hover,#f5f5f5);
  padding:.08em .35em;border-radius:4px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.92em;
}
.mod-chat .c-bubble pre{
  background:var(--ui-hover,#f5f5f5);
  border:1px solid var(--ui-border-soft,#ececec);
  border-radius:6px;padding:.55em .7em;margin:.45em 0;overflow:auto;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.92em;line-height:1.55;
  /* 覆盖父级 .c-bubble{white-space:pre-wrap}，让代码块内的换行符被尊重 */
  white-space:pre;
}
.mod-chat .c-bubble pre code{background:none;padding:0;font-size:inherit;white-space:pre}
.mod-chat .c-bubble blockquote{
  margin:.45em 0;padding:0 .8em;border-left:3px solid currentColor;
  opacity:.7;
}
.mod-chat .c-bubble blockquote > :first-child{margin-top:0}
.mod-chat .c-bubble blockquote > :last-child{margin-bottom:0}
.mod-chat .c-bubble table{
  border-collapse:collapse;margin:.45em 0;font-size:.95em;
}
.mod-chat .c-bubble th,
.mod-chat .c-bubble td{
  border:1px solid var(--ui-border-soft,#ececec);
  padding:.3em .6em;
}
.mod-chat .c-bubble tr:nth-child(2n) td{background:var(--ui-hover,#f5f5f5)}
.mod-chat .c-bubble a{color:var(--ui-accent,#0969da);text-decoration:none}
.mod-chat .c-bubble a:hover{text-decoration:underline}
.mod-chat .c-bubble hr{
  border:none;border-top:1px solid var(--ui-border-soft,#ececec);
  margin:.8em 0;
}

/* 打字中：三个跳动的小点 */
.mod-chat .c-typing{display:flex;gap:4px;align-items:center;height:18px;}
.mod-chat .c-typing i{
  width:6px;height:6px;border-radius:50%;
  background:var(--ui-faint,#9a9a9a);display:block;
  animation:c-bounce 1.2s infinite ease-in-out;
}
.mod-chat .c-typing i:nth-child(2){animation-delay:.15s;}
.mod-chat .c-typing i:nth-child(3){animation-delay:.3s;}
@keyframes c-bounce{
  0%,60%,100%{transform:translateY(0);opacity:.45;}
  30%{transform:translateY(-4px);opacity:1;}
}
@media (prefers-reduced-motion:reduce){
  .mod-chat .c-typing i{animation:none;opacity:.6;}
}

/* ---------- 空态 ---------- */
.mod-chat .c-empty{
  flex:1;min-height:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:12px;
  text-align:center;padding:40px;
}
.mod-chat .c-empty svg{
  width:40px;height:40px;stroke:var(--ui-border);fill:none;
  stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round;
}
.mod-chat .c-empty .t{
  font-size:1.1429rem;font-weight:600;line-height:1.3;color:var(--ui-muted);
}
.mod-chat .c-empty .d{
  max-width:52ch;font-size:0.9286rem;line-height:1.75;color:var(--ui-faint);
}

/* ---------- 输入区 ---------- */
.mod-chat .c-composer{
  flex:none;border-top:1px solid var(--ui-border-soft,#ececec);
  background:var(--ui-bg,#fff);
  /* 去掉快捷键提示行后，上下改为对称留白 */
  padding:14px 0;
}
.mod-chat .c-composer-inner{
  /* 输入框贴到两侧：只用 --c-gutter-box 的一点点间隔（比消息区更宽） */
  margin:0 auto;padding:0 var(--c-gutter-box);
}
/* 输入框：上下切成两部分，**中间刻意不画分割线** ——
   上半 = 正常输入（textarea + 附件），下半 = 快捷选择内容 + 按钮 */
.mod-chat .c-box{
  display:flex;flex-direction:column;
  border:1px solid var(--ui-border,#e0e0e0);
  border-radius:18px;background:var(--ui-elev,#fff);
  box-shadow:var(--ui-shadow-1,0 1px 3px rgba(0,0,0,.06));
  transition:border-color .16s,box-shadow .16s;
}
.mod-chat .c-box:focus-within{
  border-color:var(--ui-accent,#0969da);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--ui-accent,#0969da) 15%,transparent);
}
/* ---------- 上半部分：正常输入（附件与正文同行混排） ---------- */
.mod-chat .c-box-top{padding:12px 16px 2px;}
.mod-chat .c-input{
  width:100%;min-height:26px;max-height:180px;overflow-y:auto;
  border:none;outline:none;background:transparent;color:var(--ui-text,#1a1a1a);
  font:inherit;font-size:0.9286rem;line-height:1.6;
  /* 换行：pre-wrap 保留用户回车；断行必须用 word-break:break-all。
     ⚠️ 不能用 word-break:break-word，也不能用 overflow-wrap:anywhere ——
     这两个的语义都是「只有当本行没有别的断行机会时，才拆这个词」。于是
     「卡片 + 空格 + 300 个 3」时，浏览器会挑那个空格断行，把整串长字挪到
     下一行，看起来就是"附件后面莫名换行、右边空一大片"。break-all 允许在
     任意字符间断，长串才会就地填满当前行。（普通英文单词只在行尾放不下时
     才被拆，实测短句不受影响。）
     也不再加 overflow-wrap:anywhere：它会让浏览器为超长文本反复算 min-content
     固有宽度，10w+ 字时是纯负担，且 break-all 已覆盖断行需求。 */
  white-space:pre-wrap;word-break:break-all;
  padding:2px 0;scrollbar-width:thin;
}
/* 占位符：编辑区有内容（含只有附件）时由 .has-content 关掉 */
.mod-chat .c-input::before{
  content:attr(data-placeholder);color:var(--ui-faint,#9a9a9a);pointer-events:none;
}
.mod-chat .c-input.has-content::before{content:none;}
/* 行内附件卡片：与正文同一行，允许「正文 <附件> 正文」 */
.mod-chat .c-token{
  display:inline-flex;align-items:center;gap:5px;vertical-align:baseline;
  max-width:220px;margin:0 2px;padding:1px 4px 1px 7px;border-radius:6px;
  background:var(--ui-hover,#f5f5f5);border:1px solid var(--ui-border,#e4e6ea);
  font-size:0.8571rem;line-height:1.5;color:var(--ui-muted,#6b6b6b);
  cursor:default;user-select:none;
}
.mod-chat .c-token:hover{border-color:var(--ui-accent,#0969da);}
.mod-chat .c-token.up{opacity:.55;}
.mod-chat .c-token.err{border-color:var(--ui-danger,#d1242f);color:var(--ui-danger,#d1242f);}
.mod-chat .c-token .ic{
  flex:none;width:12px;height:12px;stroke:currentColor;fill:none;
  stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;
}
.mod-chat .c-token .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mod-chat .c-token .sz{flex:none;color:var(--ui-faint,#9a9a9a);}
.mod-chat .c-token .x{
  flex:none;width:15px;height:15px;padding:0;border:none;border-radius:50%;
  background:transparent;color:var(--ui-faint,#9a9a9a);cursor:pointer;
  font-size:0.8571rem;line-height:1;
  display:flex;align-items:center;justify-content:center;
}
.mod-chat .c-token .x:hover{background:var(--ui-border,#e4e6ea);color:var(--ui-text,#1a1a1a);}

/* 悬停预览浮层：图片给缩略图，文件给正文片段 */
.mod-chat .c-preview{
  position:fixed;z-index:1200;max-width:340px;
  /* 高度兜底：始终向上展开，太高就内部裁掉，避免顶出视口 */
  max-height:min(300px, 60vh);overflow:hidden;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  border:1px solid var(--ui-border,#e0e0e0);border-radius:10px;
  box-shadow:0 10px 30px rgba(0,0,0,.18);padding:10px 12px;
  font-size:0.7857rem;line-height:1.6;pointer-events:none;
}
.mod-chat .c-preview[hidden]{display:none;}
.mod-chat .c-preview img{display:block;max-width:300px;max-height:200px;border-radius:6px;}
.mod-chat .c-preview pre{
  margin:0;max-height:180px;overflow:hidden;
  white-space:pre-wrap;word-break:break-word;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:0.7857rem;
}
.mod-chat .c-preview .hd{font-weight:600;margin-bottom:4px;word-break:break-all;}
.mod-chat .c-preview .warn{color:var(--ui-danger,#d1242f);}

/* ---------- 下半部分：上传 + 模型选择 + 发送 ---------- */
.mod-chat .c-box-bottom{display:flex;align-items:center;gap:8px;padding:4px 10px 10px;}
/* 上传：左下角的「+」 */
.mod-chat .c-plus{
  flex:none;width:30px;height:30px;padding:0;border-radius:50%;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);background:var(--ui-elev,#fff);
  color:var(--ui-muted,#6b6b6b);
  display:flex;align-items:center;justify-content:center;
  transition:background .16s,color .16s,border-color .16s;
}
.mod-chat .c-plus svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;}
.mod-chat .c-plus:hover{background:var(--ui-hover);color:var(--ui-text);border-color:var(--ui-accent,#0969da);}
/* 模型选择框：底行、发送按钮左侧（靠右对齐由 margin-left:auto 完成） */
.mod-chat .c-model{
  flex:none;max-width:160px;margin-left:auto;
  height:22px;padding:0 8px;border-radius:6px;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);background:var(--ui-elev,#fff);
  color:var(--ui-muted,#6b6b6b);
  font-family:inherit;font-size:0.7143rem;
  text-overflow:ellipsis;
  transition:background .16s,color .16s,border-color .16s;
}
.mod-chat .c-model:hover{background:var(--ui-hover);color:var(--ui-text);border-color:var(--ui-accent,#0969da);}
.mod-chat .c-model:focus{outline:none;border-color:var(--ui-accent,#0969da);}
.mod-chat .c-model[hidden]{display:none;}
/* token 卡片：放在信息栏（上下文右侧），点开看明细。宽度下限 = 实测 76px × 1.2 */
.mod-chat .c-tok{
  flex:none;display:flex;align-items:center;justify-content:flex-start;gap:5px;
  min-width:92px;height:24px;padding:0 10px;border-radius:6px;cursor:pointer;
  border:1px solid var(--ui-border,#e0e0e0);background:var(--ui-elev,#fff);
  color:var(--ui-muted,#6b6b6b);font-family:inherit;font-size:0.7857rem;
  font-variant-numeric:tabular-nums;
  transition:background .16s,color .16s,border-color .16s;
}
.mod-chat .c-tok:hover,.mod-chat .c-tok.on{
  background:var(--ui-hover);color:var(--ui-text);border-color:var(--ui-accent,#0969da);
}
.mod-chat .c-tok b{font-weight:600;color:var(--ui-text);}

/* token 明细浮层：上层总体可视化 + 下层垂直明细 */
.mod-chat .c-tokpanel{
  position:fixed;z-index:1300;width:264px;
  background:var(--ui-elev,#fff);color:var(--ui-text,#1a1a1a);
  border:1px solid var(--ui-border,#e0e0e0);border-radius:12px;
  box-shadow:0 12px 32px rgba(0,0,0,.18);padding:14px;
  font-size:0.7857rem;
}
.mod-chat .c-tokpanel[hidden]{display:none;}
.mod-chat .c-tokpanel .cap{color:var(--ui-faint,#9a9a9a);}
.mod-chat .c-tokpanel .big{
  font-size:1.5714rem;font-weight:700;line-height:1.15;letter-spacing:-.01em;
  font-variant-numeric:tabular-nums;
}
.mod-chat .c-tokpanel .big em{font-size:0.7857rem;font-style:normal;font-weight:400;color:var(--ui-faint,#9a9a9a);margin-left:4px;}
.mod-chat .c-tokpanel .rate{
  display:inline-block;margin-left:6px;padding:1px 6px;border-radius:999px;
  background:color-mix(in srgb,var(--ui-accent,#0969da) 12%,transparent);
  color:var(--ui-accent,#0969da);font-weight:600;
}
.mod-chat .c-tokpanel .stack{
  display:flex;height:8px;margin:10px 0 8px;border-radius:4px;overflow:hidden;
  background:var(--ui-border-soft,#ececec);
}
.mod-chat .c-tokpanel .stack > i{display:block;height:100%;}
.mod-chat .c-tokpanel .legend{display:flex;flex-wrap:wrap;gap:4px 12px;color:var(--ui-faint,#9a9a9a);}
.mod-chat .c-tokpanel .legend em{
  display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px;
}
.mod-chat .c-tokpanel .rows{
  margin-top:12px;padding-top:10px;border-top:1px solid var(--ui-border-soft,#ececec);
  display:flex;flex-direction:column;gap:7px;
}
.mod-chat .c-tokpanel .row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;}
.mod-chat .c-tokpanel .row span{color:var(--ui-faint,#9a9a9a);}
.mod-chat .c-tokpanel .row b{font-weight:600;font-variant-numeric:tabular-nums;}
.mod-chat .c-tokpanel .row u{
  text-decoration:none;margin-left:4px;padding:0 4px;border-radius:4px;
  background:var(--ui-hover,#f5f5f5);color:var(--ui-faint,#9a9a9a);font-size:0.7143rem;
}
/* 发送：右下角的小圆钮 */
.mod-chat .c-send{
  flex:none;width:32px;height:32px;border:none;border-radius:50%;
  background:var(--ui-accent-solid,#0969da);color:var(--ui-on-accent,#fff);cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  transition:opacity .16s,transform .16s;
}
.mod-chat .c-send svg{
  width:16px;height:16px;stroke:currentColor;fill:none;
  stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;
}
.mod-chat .c-send:hover{opacity:.88;}
.mod-chat .c-send:active{transform:scale(.94);}
.mod-chat .c-send:disabled{opacity:.35;cursor:not-allowed;transform:none;}

/* ---------- 信息栏（上下文圆环 + 模型选择框） ---------- */
.mod-chat .c-info{
  display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;
  margin-top:6px;padding:0 6px;
  font-size:0.7143rem;line-height:1.5;color:var(--ui-faint,#9a9a9a);
  font-variant-numeric:tabular-nums;
}
.mod-chat .c-info i{font-style:normal;color:var(--ui-muted,#6b6b6b);}
.mod-chat .c-info b{font-weight:600;color:var(--ui-text,#1a1a1a);}
/* 上下文占用：只留圆形可视化，点圆环展开明细 */
.mod-chat .c-info .ctx{display:inline-flex;align-items:center;}
.mod-chat .c-ctxbtn{
  display:flex;align-items:center;padding:0;border:none;background:transparent;
  cursor:pointer;border-radius:50%;
}
.mod-chat .c-ctxbtn:focus-visible{outline:2px solid var(--ui-accent,#0969da);outline-offset:2px;}
/* 圆环通用样式（信息栏小环 / 面板大环共用） */
.mod-chat .ring .bg{stroke:var(--ui-border-soft,#ececec);fill:none;}
.mod-chat .ring .fg{stroke:var(--ui-accent,#0969da);fill:none;
  transition:stroke-dashoffset .3s ease,stroke .3s ease;}
.mod-chat .ring.warn .fg{stroke:#d29922;}
.mod-chat .ring.danger .fg{stroke:var(--ui-danger,#d1242f);}
/* 面板顶部的大圆环 + 右侧读数 */
.mod-chat .c-tokpanel .ringwrap{display:flex;align-items:center;gap:14px;margin-bottom:12px;}
.mod-chat .c-tokpanel .big-ring{position:relative;flex:none;width:58px;height:58px;}
.mod-chat .c-tokpanel .big-ring svg{display:block;width:58px;height:58px;}
.mod-chat .c-tokpanel .big-ring .pct{
  position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:0.9286rem;font-weight:700;color:var(--ui-text,#1a1a1a);
  font-variant-numeric:tabular-nums;
}
.mod-chat .c-tokpanel .ringwrap .side{display:flex;flex-direction:column;gap:3px;min-width:0;}
.mod-chat .c-tokpanel .ringwrap .side .k{color:var(--ui-faint,#9a9a9a);}
.mod-chat .c-tokpanel .ringwrap .side .v{
  font-size:1.1429rem;font-weight:700;color:var(--ui-text,#1a1a1a);
  font-variant-numeric:tabular-nums;
}
.mod-chat .c-tokpanel .sub{
  margin-top:2px;padding-top:8px;border-top:1px dashed var(--ui-border-soft,#ececec);
  color:var(--ui-faint,#9a9a9a);
}

/* 窄窗口下收紧边距，避免内容被挤扁 */
@media (max-width:560px){
  .mod-chat{--c-gutter:14px;--c-gutter-box:6px;}
  .mod-chat .c-model{max-width:40%;}
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

/* 发送图标：向上箭头（配合圆形按钮，见 .c-send 的 border-radius:50%） */
const SEND_ICON =
  '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>';

/** 输入框自适应高度上限（px），与 CSS 的 max-height 必须一致 */
const MAX_INPUT_H = 180;

/**
 * 对话后端（P.A.L.M LLM 内核，FastAPI @ 10093）。
 * SSE 流式：事件 meta / reasoning / token / done / error，以 `data: [DONE]` 收尾。
 * 该后端 CORS 已允许 http://localhost:5173，可直接跨端口调用。
 */
// 后端地址只保留 kernel-api.js 一处（KERNEL_BASE），避免改了这头忘了那头
const CHAT_API = KERNEL_BASE + '/api/chat/stream';

/** 聊天行为偏好（设置页「聊天」子页实时写入，这里首屏读取并订阅变更） */
function readChatPref(key, def) {
  try {
    const raw = localStorage.getItem('webui.chat.' + key);
    return raw === null ? def : (raw === '1' || raw === 'true');
  } catch (e) { return def; }
}
const chatPrefs = {
  enterSend: readChatPref('enterSend', true),
  autoScroll: readChatPref('autoScroll', true),
  showTime: readChatPref('showTime', true),
  showTokenStats: readChatPref('showTokenStats', true),
  showDetailInfo: readChatPref('showDetailInfo', true),
};

/** 把时间戳格式化成 HH:MM */
function hhmm(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes());
}

/** 把时间戳格式化成 HH:MM:SS（回合统计里的「请求时间」） */
function hhmmss(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}

export default async function mount(host) {
  injectStyle();

  // ---- 加载 Markdown 解析依赖（marked + DOMPurify + hljs）----
  // 沿用渲染器运行时加载的 vendor，不重复请求；失败时回退纯文本。
  let mdReady = false;
  try {
    const api = await import('../../core/renderers/index.js');
    await api.ensureRenderers();
    if (window.marked && window.DOMPurify) mdReady = true;
  } catch (e) {
    console.error('[Chat] Markdown 解析器加载失败，回退纯文本：', e);
    mdReady = false;
  }

  /**
   * 把 Markdown 文本渲染成安全的 HTML。
   * 返回 null 表示本次渲染失败，调用方应回退到 textContent。
   */
  function renderMd(text) {
    if (!mdReady) return null;
    try {
      const html = window.DOMPurify.sanitize(window.marked.parse(text || ''));
      return html;
    } catch (e) {
      console.error('[Chat] Markdown 渲染失败：', e);
      return null;
    }
  }

  /** 给渲染好的代码块跑 hljs 高亮（依赖就绪时才有意义）*/
  function highlightCode(root) {
    if (!window.hljs) return;
    root.querySelectorAll('pre code').forEach((c) => {
      try { hljs.highlightElement(c); } catch (e) {}
    });
  }

  host.innerHTML = `
    <div class="mod-chat">
      <div class="c-list" data-list>
        <div class="c-inner" data-inner></div>
        <div class="c-empty" data-empty>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20.5 11.6c0 4.2-3.8 7.6-8.5 7.6a9.7 9.7 0 0 1-2.9-.4L4 20.5l1.4-3.7A7.2 7.2 0 0 1 3.5 11.6C3.5 7.4 7.3 4 12 4s8.5 3.4 8.5 7.6z"/>
          </svg>
          <div class="t">开始对话</div>
          <div class="d">在下面输入消息，按 Enter 发送<br>Shift + Enter 换行<br>回复支持 **Markdown 渲染**（对接 P.A.L.M 对话后端）</div>
        </div>
      </div>

      <div class="c-composer">
        <div class="c-composer-inner">
          <div class="c-box">
            <!-- 上半部分：正常输入（附件与正文同行混排） -->
            <div class="c-box-top">
              <div class="c-input" data-input contenteditable="true" role="textbox"
                   aria-multiline="true" aria-label="消息输入框"
                   spellcheck="false" autocorrect="off" autocapitalize="off"
                   data-placeholder="输入消息…"></div>
            </div>
            <!-- 下半部分：上传 + 模型选择 + 发送（无分割线） -->
            <div class="c-box-bottom">
              <button class="c-plus" data-upload type="button"
                title="上传文件" aria-label="上传文件">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
              </button>
              <select class="c-model" data-model title="选择模型"
                aria-label="选择模型" hidden></select>
              <button class="c-send" data-send type="button"
                title="发送" aria-label="发送" disabled>
                <svg viewBox="0 0 24 24" aria-hidden="true">${SEND_ICON}</svg>
              </button>
            </div>
            <input type="file" data-file multiple hidden />
          </div>
          <!-- 信息栏：上下文（圆环） + token 卡片（同行） -->
          <div class="c-info" data-info>
            <span class="ctx" data-ctx></span>
            <button class="c-tok" data-tok type="button"
              title="token 用量详情" aria-label="token 用量详情"
              aria-expanded="false">
              <span class="cap">token</span><b data-toknum>0</b>
            </button>
          </div>
        </div>
      </div>
      <!-- 附件悬停预览浮层（放在 contenteditable 之外，避免被当成正文） -->
      <div class="c-preview" data-preview hidden></div>
      <!-- token 明细浮层 / 上下文明细浮层（两者同款样式） -->
      <div class="c-tokpanel" data-tokpanel hidden></div>
      <div class="c-tokpanel" data-ctxpanel hidden></div>
    </div>`;

  const listEl = host.querySelector('[data-list]');
  const innerEl = host.querySelector('[data-inner]');
  const emptyEl = host.querySelector('[data-empty]');
  const inputEl = host.querySelector('[data-input]');
  const sendEl = host.querySelector('[data-send]');
  const previewEl = host.querySelector('[data-preview]');
  const infoEl = host.querySelector('[data-info]');
  const infoCtxEl = host.querySelector('[data-ctx]');
  const modelSel = host.querySelector('[data-model]');
  const tokEl = host.querySelector('[data-tok]');
  const tokNumEl = host.querySelector('[data-toknum]');
  const tokPanelEl = host.querySelector('[data-tokpanel]');
  const ctxPanelEl = host.querySelector('[data-ctxpanel]');
  const fileInput = host.querySelector('[data-file]');
  const uploadBtn = host.querySelector('[data-upload]');
  const rootEl = host.querySelector('.mod-chat');   // no-time 类挂这里，配合 .mod-chat.no-time 选择器

  let busy = false;              // 助手「正在输入」时禁止发送
  let cancelReply = null;        // 进行中的回复清理句柄（切页/销毁时取消）
  let conversationId = null;     // 后端会话 id（首次 meta 事件带回，之后带上以保持上下文）
  /* 待发送的附件（内存态）。文件本体已由**后端存储**（uploads/<日期>/<批次>/），
     这里只留展示与发送所需的信息：
       tid 编辑区里那张卡片的标识；status uploading/ready/error
       dataUri 本地副本（图片缩略图、以及"发本体"策略要用）
       url/absUrl 后端地址；preview/text 后端抽出的正文片段与全文 */
  let attachments = [];

  /* 信息栏 / token 卡片数据：sessTok 累计本次会话，lastStats 是最近一轮的归一统计。
     口径（见内核 providers/_telemetry.py）：input_tokens **不含**缓存命中，
     total = 非缓存输入 + 缓存读 + 缓存写 + 输出。 */
  const sessTok = { input: 0, cache: 0, cacheWrite: 0, output: 0, total: 0 };
  let lastStats = null;
  /* 上下文占用分布的估算依据：内核只给总输入 token，不给分类，
     所以按各部分的**字符占比**把实测输入 token 分摊下去（见 ctxParts）。
     sysChars / toolsChars 来自内核 config，msgs 记录每条消息的字符数。 */
  let sysChars = 0;
  let toolsChars = 0;
  const msgs = [];

  /* ---------- 渲染 ---------- */
  function syncEmpty() {
    const has = innerEl.childElementCount > 0;
    emptyEl.style.display = has ? 'none' : '';
    listEl.style.overflowY = has ? 'auto' : 'hidden';
  }

  function syncSend() {
    // 有附件（即使没文字）也允许发送
    sendEl.disabled = busy || (!inputText().trim() && attachments.length === 0);
  }

  /* ---------- 输入区（contenteditable，附件与正文同行混排） ---------- */

  /** 把编辑区拆成**有序**片段：正文与附件保持用户看到的先后顺序，
   *  这样发送时才能还原成「正文 <附件> 正文」。 */
  function readSegments() {
    const segs = [];
    let buf = '';
    const flush = () => {
      if (buf) {
        // 卡片后垫的 nbsp 在这里归一成普通空格，别把 &nbsp; 发进消息
        segs.push({ type: 'text', value: buf.replace(/\u00a0/g, ' ') });
        buf = '';
      }
    };
    const walk = (node) => {
      Array.prototype.forEach.call(node.childNodes, (child) => {
        if (child.nodeType === 3) { buf += child.nodeValue; return; }   // 文本
        if (child.nodeType !== 1) return;
        const el = child;
        if (el.dataset && el.dataset.tid) { flush(); segs.push({ type: 'file', tid: el.dataset.tid }); return; }
        if (el.tagName === 'BR') { buf += '\n'; return; }
        // contenteditable 里回车常被包成 <div>/<p>，按块级元素补换行
        const block = el.tagName === 'DIV' || el.tagName === 'P';
        if (block && buf && !/\n$/.test(buf)) buf += '\n';
        walk(el);
        if (block) buf += '\n';
      });
    };
    walk(inputEl);
    flush();
    return segs;
  }

  /** 只要纯文本部分（空判、字数统计用） */
  function inputText() {
    return readSegments().filter((s) => s.type === 'text').map((s) => s.value).join('');
  }

  /** 占位符：有内容（含只有附件）就藏掉 */
  function syncPlaceholder() {
    const has = inputEl.textContent.length > 0 || !!inputEl.querySelector('.c-token');
    inputEl.classList.toggle('has-content', has);
  }

  /* ---------- 附件 ---------- */
  const fmtSize = (n) => {
    if (!n) return '';
    if (n < 1024) return n + 'B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + 'KB';
    return (n / 1024 / 1024).toFixed(1) + 'MB';
  };

  const fileIcon = (kind) => (kind === 'image'
    ? '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.4"/><path d="m4 17 5-5 4 4 3-3 4 4"/>'
    : '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>');

  const findAtt = (tid) => attachments.filter((a) => a.tid === tid)[0] || null;

  /* 常见后缀 → 规范 MIME。
     内核按 MIME 白名单校验（`_capability.py::_mime_allowed` 是**精确匹配或
     `type/*` 通配**），而各家 doc_mimes 很窄（glm=pdf/msword/text-plain、
     openai 只有 pdf）。浏览器对 .md/.csv/.json 这类常常给不出类型、回落成
     application/octet-stream，会被内核直接拒掉。这里按后缀归一：
     文本类统一标 text/plain，才落得进白名单。图片保持 image/* 不动。 */
  const MIME_BY_EXT = {
    txt: 'text/plain', text: 'text/plain', log: 'text/plain', ini: 'text/plain',
    cfg: 'text/plain', conf: 'text/plain', toml: 'text/plain', env: 'text/plain',
    md: 'text/plain', markdown: 'text/plain', rst: 'text/plain',
    json: 'text/plain', yaml: 'text/plain', yml: 'text/plain', csv: 'text/plain',
    py: 'text/plain', js: 'text/plain', ts: 'text/plain', tsx: 'text/plain',
    jsx: 'text/plain', java: 'text/plain', c: 'text/plain', h: 'text/plain',
    cpp: 'text/plain', go: 'text/plain', rs: 'text/plain', sh: 'text/plain',
    sql: 'text/plain', html: 'text/plain', css: 'text/plain', xml: 'text/plain',
    pdf: 'application/pdf',
    doc: 'application/msword',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    xls: 'application/vnd.ms-excel',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  };

  function normalizeMime(name, mime) {
    const ext = String(name || '').split('.').pop().toLowerCase();
    if (MIME_BY_EXT[ext]) return MIME_BY_EXT[ext];
    if (mime && mime !== 'application/octet-stream') return mime;
    return mime || 'application/octet-stream';
  }

  /** 造一张行内附件卡片 */
  function tokenEl(a) {
    const el = document.createElement('span');
    el.className = 'c-token'
      + (a.status === 'uploading' ? ' up' : (a.status === 'error' ? ' err' : ''));
    el.contentEditable = 'false';                 // 卡片整体不可编辑，但可随正文移动
    el.dataset.tid = a.tid;
    el.title = a.status === 'error' ? (a.error || '上传失败')
      : (a.status === 'uploading' ? '上传中…' : (a.textError || '已存到后端，鼠标悬停可预览'));
    el.innerHTML = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">' + fileIcon(a.kind) + '</svg>'
      + '<span class="nm"></span><span class="sz"></span>'
      + '<button class="x" type="button" data-rm="' + a.tid + '" aria-label="移除附件">×</button>';
    el.querySelector('.nm').textContent = a.name;
    el.querySelector('.sz').textContent = a.status === 'uploading' ? '上传中…' : fmtSize(a.size);
    return el;
  }

  /** 在光标处插入若干张卡片（**一次性插一个片段**，保证多选时卡片相邻且有序）；
   *  光标不在编辑区内则追加到末尾。 */
  function insertTokens(tids) {
    const frag = document.createDocumentFragment();
    tids.forEach((tid) => {
      const a = findAtt(tid);
      if (!a) return;
      frag.appendChild(tokenEl(a));
      /* 卡片后垫**普通空格**（不是 &nbsp;）。
         ⚠️ 用 &nbsp; 会把「卡片 + 后面那串字」粘成一个不可断的整体，浏览器
         只好把整串挪到下一行 —— 表现为"卡片后突然换行"。普通空格既给了断行
         机会，又能让长串就地填满当前行；.c-input 是 pre-wrap，空格不会被吃掉。 */
      frag.appendChild(document.createTextNode(' '));
    });
    if (!frag.childNodes.length) return;
    const tail = frag.lastChild;              // 末尾那个空格，作为光标锚点

    const sel = window.getSelection();
    let range = null;
    if (sel && sel.rangeCount) {
      const r = sel.getRangeAt(0);
      if (inputEl.contains(r.startContainer)) range = r;
    }
    if (!range) {
      range = document.createRange();
      range.selectNodeContents(inputEl);
      range.collapse(false);
    }
    range.deleteContents();
    range.insertNode(frag);
    // insertNode 对 range 的影响依实现而异，这里显式把光标钉到末尾空格之后
    const after = document.createRange();
    after.setStart(tail, tail.length);
    after.collapse(true);
    if (sel) { sel.removeAllRanges(); sel.addRange(after); }
    syncPlaceholder();
    autoGrow();
    syncSend();
  }

  /** 上传完成后刷新那张卡片的态。
   *  **只改类名/文案，不重建节点** —— 在获得焦点的 contenteditable 里
   *  替换节点会把光标冲回开头（实测：后续输入会插到第一张卡片之前）。 */
  function refreshToken(a) {
    const el = inputEl.querySelector('.c-token[data-tid="' + a.tid + '"]');
    if (!el) return;
    el.classList.toggle('up', a.status === 'uploading');
    el.classList.toggle('err', a.status === 'error');
    el.title = a.status === 'error' ? (a.error || '上传失败')
      : (a.status === 'uploading' ? '上传中…' : (a.textError || '已存到后端，鼠标悬停可预览'));
    const sz = el.querySelector('.sz');
    if (sz) sz.textContent = a.status === 'uploading' ? '上传中…' : fmtSize(a.size);
  }

  /** 选文件 → 立刻上传到后端存储，同时本地读一份 data URI（缩略图 / 发本体用） */
  async function pickFiles(fileList) {
    const arr = Array.from(fileList || []);
    if (!arr.length) return;
    const batch = [];
    arr.forEach((f) => {
      const a = {
        tid: 'a_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6),
        name: f.name,
        size: f.size,
        mime: f.type || 'application/octet-stream',
        kind: (f.type || '').indexOf('image/') === 0 ? 'image' : 'other',
        status: 'uploading',
        error: '',
        dataUri: '', thumbUrl: '',
        url: '', absUrl: '', preview: '', text: '', textError: '',
      };
      attachments.push(a);
      batch.push(a);
      const rd = new FileReader();
      rd.onload = () => {
        a.dataUri = String(rd.result || '');
        if (a.kind === 'image') a.thumbUrl = a.dataUri;
      };
      rd.readAsDataURL(f);
    });
    insertTokens(batch.map((a) => a.tid));     // 一次性插入，保证多选时相邻有序

    const fd = new FormData();
    batch.forEach((a, i) => fd.append('files', arr[i], arr[i].name));
    try {
      const res = await fetch(KERNEL_BASE + '/api/uploads', { method: 'POST', body: fd });
      if (!res.ok) {
        let msg = 'HTTP ' + res.status;
        try { const j = await res.json(); if (j && j.detail) msg = String(j.detail); } catch (e) { /* 保持原样 */ }
        throw new Error(msg);
      }
      const data = await res.json();
      (data.files || []).forEach((f, i) => {
        const a = batch[i];                        // 后端按提交顺序回传，按下标配对
        if (!a) return;
        a.status = 'ready';
        a.url = f.url || '';
        a.absUrl = f.abs_url || '';
        // MIME 归一：浏览器给不出类型时按后缀补成内核认的值（见 MIME_BY_EXT）
        a.mime = normalizeMime(a.name, f.mime || a.mime);
        a.kind = f.kind || a.kind;
        a.preview = f.preview || '';
        a.text = f.text || '';
        a.textError = f.text_error || '';
        refreshToken(a);
      });
      syncSend();
    } catch (e) {
      const msg = e && e.message ? e.message : String(e);
      batch.forEach((a) => { a.status = 'error'; a.error = msg; refreshToken(a); });
    }
  }

  function removeAttachment(tid) {
    attachments = attachments.filter((a) => a.tid !== tid);
    const el = inputEl.querySelector('.c-token[data-tid="' + tid + '"]');
    if (el) el.remove();
    hidePreview();
    syncPlaceholder();
    autoGrow();
    syncSend();
  }

  /* ---------- 悬停预览（图片给缩略图，文件给正文片段） ---------- */
  let hoverTid = '';
  let previewImg = null;

  /** 统一**向上**展开：用 bottom 锚定，底边始终贴在卡片上方。
   *  这样内容多高都只往上长，图片异步解码后高度变大也不会跳位、更不会翻到下方
   *  （之前用 top 定位，首次悬停时图片还没解码、高度算成 0，就"顶不下"翻到下面去了）。 */
  function placePreview(el) {
    const r = el.getBoundingClientRect();
    const pr = previewEl.getBoundingClientRect();
    let bottom = window.innerHeight - r.top + 8;
    // 顶到视口就贴边，但**不翻转**方向
    bottom = Math.min(bottom, Math.max(8, window.innerHeight - pr.height - 8));
    previewEl.style.top = 'auto';
    previewEl.style.bottom = Math.round(bottom) + 'px';
    const left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - pr.width - 8));
    previewEl.style.left = Math.round(left) + 'px';
  }

  function showPreview(el, a) {
    if (!a) return;
    previewEl.innerHTML = '';
    previewImg = null;

    const hd = document.createElement('div');
    hd.className = 'hd';
    hd.textContent = a.name + (a.size ? ' · ' + fmtSize(a.size) : '');
    previewEl.appendChild(hd);

    if (a.kind === 'image' && a.thumbUrl) {
      const img = document.createElement('img');
      img.src = a.thumbUrl;
      img.alt = a.name;
      previewImg = img;
      previewEl.appendChild(img);
    } else if (a.status === 'uploading') {
      const p = document.createElement('div');
      p.textContent = '上传中…';
      previewEl.appendChild(p);
    } else if (a.status === 'error') {
      const p = document.createElement('div');
      p.className = 'warn';
      p.textContent = a.error || '上传失败';
      previewEl.appendChild(p);
    } else if (a.preview) {
      const pre = document.createElement('pre');
      pre.textContent = a.preview;
      previewEl.appendChild(pre);
    } else {
      const p = document.createElement('div');
      p.className = 'warn';
      p.textContent = a.textError || '没有可预览的正文';
      previewEl.appendChild(p);
    }

    previewEl.hidden = false;
    placePreview(el);
    // 图片解码是异步的：就绪后再定位一次（bottom 锚定下只会往上长）
    if (previewImg) {
      const re = () => { if (hoverTid) placePreview(el); };
      if (previewImg.complete) re();
      else {
        previewImg.addEventListener('load', re, { once: true });
        previewImg.addEventListener('error', re, { once: true });
      }
    }
  }

  function hidePreview() {
    hoverTid = '';
    previewImg = null;
    previewEl.hidden = true;
    previewEl.innerHTML = '';
  }

  /* ---------- 按模型能力决定「附件怎么发」 ---------- */
  let modelCaps = { known: false, canUpload: false, canTools: false, model: '', provider: '', ctx: 0 };

  /* ---------- 模型选择框（发送按钮左侧） ---------- */
  const MODEL_SEP = '|||';

  /** 把配置里的 provider/models 铺成 <optgroup> 下拉 */
  function renderModelSelect(cfg) {
    const providers = (cfg && cfg.providers) || [];
    const cur = ((cfg && cfg.active_provider) || '') + MODEL_SEP + ((cfg && cfg.active_model) || '');
    modelSel.innerHTML = '';
    let n = 0;
    providers.forEach((p) => {
      const models = Array.isArray(p.models) ? p.models : [];
      if (!models.length) return;
      const g = document.createElement('optgroup');
      g.label = p.name || p.id;
      models.forEach((m) => {
        const o = document.createElement('option');
        o.value = p.id + MODEL_SEP + m;
        o.textContent = m;
        if (p.id + MODEL_SEP + m === cur) o.selected = true;
        g.appendChild(o);
        n += 1;
      });
      modelSel.appendChild(g);
    });
    modelSel.hidden = n === 0;      // 一个模型都没有就不占位
  }

  /** 切换模型：写回内核配置（单一事实来源 —— 设置页读的是同一份） */
  async function switchModel(value) {
    const i = String(value).indexOf(MODEL_SEP);
    if (i < 0) return;
    const pid = value.slice(0, i);
    const mid = value.slice(i + MODEL_SEP.length);
    modelSel.disabled = true;
    try {
      const cfg = await getConfig();
      cfg.active_provider = pid;
      cfg.active_model = mid;
      const res = await fetch(KERNEL_BASE + '/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: cfg }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
    } catch (e) {
      console.error('[Chat] 切换模型失败：', e);
    } finally {
      modelSel.disabled = false;
    }
    await refreshModelState();      // 重读配置 → 刷新能力 / 上下文上限 / 下拉选中项
  }

  /* ---------- 信息栏：上下文占用 / token / 首字延迟 / 输出速度 ---------- */
  const fmtTok = (n) => {
    const v = Number(n) || 0;
    if (v < 1000) return String(v);
    if (v < 1000000) return (v / 1000).toFixed(v < 10000 ? 1 : 0) + 'K';
    return (v / 1000000).toFixed(2) + 'M';
  };

    /** 上下文读数：上限 / 已用 / 占比 / 档位。
   *  分母来自「设置 → 模型信息」里填的上下文长度；云端模型内核不提供该值
   *  （Profile 只有 max_output），没填就是未设置。 */
  function ctxNumbers() {
    const lim = modelCaps.ctx || 0;
    const used = lastStats
      ? (lastStats.input_tokens || 0) + (lastStats.cache_read_tokens || 0)
        + (lastStats.output_tokens || 0)
      : 0;
    const pct = lim ? Math.min(100, used / lim * 100) : 0;
    const lvl = pct >= 90 ? 'danger' : (pct >= 70 ? 'warn' : '');
    return { lim: lim, used: used, pct: pct, lvl: lvl };
  }

  /** 造圆环 SVG：周长 = 2πr，画满 pct% 的弧 → dasharray=周长、dashoffset=周长×(1−pct/100)。
   *  `rotate(-90 cx cy)` 把起点从 3 点方向挪到 12 点方向（圆环默认从右侧起算）。 */
  function ringSvg(cls, r, sw, size, pct) {
    const c = 2 * Math.PI * r;
    const mid = size / 2;
    return '<svg class="' + cls + '" viewBox="0 0 ' + size + ' ' + size + '" width="' + size
      + '" height="' + size + '" aria-hidden="true">'
      + '<circle cx="' + mid + '" cy="' + mid + '" r="' + r + '" stroke-width="' + sw + '" class="bg"/>'
      + '<circle cx="' + mid + '" cy="' + mid + '" r="' + r + '" stroke-width="' + sw
      + '" stroke-linecap="round" transform="rotate(-90 ' + mid + ' ' + mid + ')"'
      + ' stroke-dasharray="' + c.toFixed(3) + '" stroke-dashoffset="'
      + (c * (1 - pct / 100)).toFixed(3) + '" class="fg"/>'
      + '</svg>';
  }

  /** 信息栏左侧：只放一个圆环，点开看明细 */
  function renderInfo() {
    const n = ctxNumbers();
    const title = n.lim
      ? '上下文占用 ' + n.pct.toFixed(1) + '%（' + n.used + ' / ' + n.lim + '）— 点击查看明细'
      : '未设置该模型的上下文上限 — 到「设置 → 模型信息」填「上下文长度」后显示占用比例';
    infoCtxEl.innerHTML = '<button class="c-ctxbtn" data-ctxbtn type="button"'
      + ' title="' + title + '" aria-label="上下文占用明细" aria-expanded="false">'
      + ringSvg('ring ' + n.lvl, 10, 3, 22, n.pct) + '</button>';
    if (!ctxPanelEl.hidden) renderCtxPanel();
  }

  /** 上下文占用分布的三类配色（与 token 面板同款调色板） */
  const CTX_COLORS = {
    prompt: 'var(--ui-accent,#0969da)',   // 提示词
    history: '#2da44e',                   // 历史记录
    tools: '#bf8700',                     // 工具调用
  };

  /** 上下文占用分布估算（提示词 / 历史记录 / 工具调用）。
   *  内核只回传「总输入 token」（input + cache_read），不区分这三类，
   *  故按各部分的**字符占比**把实测输入 token 摊分下去：
   *    提示词   ← cfg.system_prompt 长度（sysChars）
   *    历史记录 ← 全部消息累计字符数（msgs 累加）
   *    工具调用 ← 工具相关字符（toolsChars，本页不渲染工具，通常 0）
   *  返回三类各自的「估算 token 数」「占比」「堆叠条宽度」，占比之和恒为 100%。 */
  function ctxParts() {
    const L = lastStats || {};
    const base = (L.input_tokens || 0) + (L.cache_read_tokens || 0);  // 输入侧 token
    const sys = sysChars || 0;
    const hist = msgs.reduce((s, m) => s + (m.chars || 0), 0);
    const tools = toolsChars || 0;
    const tot = sys + hist + tools;
    const tok = (v) => (base && tot ? Math.round(v / tot * base) : 0);
    const pct = (v) => (base && tot ? (v / tot * 100).toFixed(1) + '%' : '-');
    const wid = (v) => (base && tot ? (v / tot * 100).toFixed(1) : '0');
    return {
      base,
      sys: tok(sys), hist: tok(hist), tools: tok(tools),
      sysPct: pct(sys), histPct: pct(hist), toolsPct: pct(tools),
      sysW: wid(sys), histW: wid(hist), toolsW: wid(tools),
    };
  }

  /** 上下文明细面板：样式与 token 面板同款
   *  上层 = 大圆环 + 读数，下层 = 垂直明细（总/当前/占用率 + 占用分布） */
  function renderCtxPanel() {
    const n = ctxNumbers();
    const p = ctxParts();
    const row = (label, val, tag) => '<div class="row"><span>' + label
      + (tag ? '<u>' + tag + '</u>' : '') + '</span><b>' + val + '</b></div>';

    ctxPanelEl.innerHTML =
      '<div class="ringwrap">'
      + '<div class="big-ring">' + ringSvg('ring ' + n.lvl, 24, 5, 58, n.pct)
      + '<span class="pct">' + n.pct.toFixed(1) + '%</span></div>'
      + '<div class="side">'
      + '<span class="k">当前上下文</span><span class="v">' + fmtTok(n.used) + '</span>'
      + '<span class="k">总上下文 ' + (n.lim ? fmtTok(n.lim) : '未设置') + '</span>'
      + '</div></div>'
      + '<div class="rows">'
      + row('总上下文', n.lim ? fmtTok(n.lim) : '未设置')
      + row('当前上下文', fmtTok(n.used))
      + row('占用率', n.pct.toFixed(1) + '%')
      + '</div>'
      + '<div class="sub">当前上下文占用分布（按字符占比估算）</div>'
      + '<div class="stack">'
      + '<i style="width:' + p.sysW + '%;background:' + CTX_COLORS.prompt + '"></i>'
      + '<i style="width:' + p.histW + '%;background:' + CTX_COLORS.history + '"></i>'
      + '<i style="width:' + p.toolsW + '%;background:' + CTX_COLORS.tools + '"></i>'
      + '</div>'
      + '<div class="legend">'
      + '<span><em style="background:' + CTX_COLORS.prompt + '"></em>提示词 ' + fmtTok(p.sys) + '</span>'
      + '<span><em style="background:' + CTX_COLORS.history + '"></em>历史记录 ' + fmtTok(p.hist) + '</span>'
      + '<span><em style="background:' + CTX_COLORS.tools + '"></em>工具调用 ' + fmtTok(p.tools) + '</span>'
      + '</div>'
      + '<div class="rows">'
      + row('提示词', lastStats ? fmtTok(p.sys) + '　' + p.sysPct : '-')
      + row('历史记录', lastStats ? fmtTok(p.hist) + '　' + p.histPct : '-')
      + row('工具调用', lastStats ? fmtTok(p.tools) + '　' + p.toolsPct : '-')
      + '</div>';
  }

  /** 与 token 面板同款：bottom 锚定 → 统一向上展开 */
  function placeCtxPanel() {
    const btn = infoCtxEl.querySelector('[data-ctxbtn]');
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const pr = ctxPanelEl.getBoundingClientRect();
    let bottom = window.innerHeight - r.top + 8;
    bottom = Math.min(bottom, Math.max(8, window.innerHeight - pr.height - 8));
    ctxPanelEl.style.top = 'auto';
    ctxPanelEl.style.bottom = Math.round(bottom) + 'px';
    const left = Math.min(Math.max(8, r.left - 20),
                          Math.max(8, window.innerWidth - pr.width - 8));
    ctxPanelEl.style.left = Math.round(left) + 'px';
  }

  function openCtxPanel() {
    renderCtxPanel();
    ctxPanelEl.hidden = false;
    const btn = infoCtxEl.querySelector('[data-ctxbtn]');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    placeCtxPanel();
  }

  function closeCtxPanel() {
    ctxPanelEl.hidden = true;
    const btn = infoCtxEl.querySelector('[data-ctxbtn]');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  const toggleCtxPanel = () => { if (ctxPanelEl.hidden) openCtxPanel(); else closeCtxPanel(); };
  const closePanels = () => { closeTokPanel(); closeCtxPanel(); };

  /* ---------- token 卡片：默认只显示总用量，点开看全部明细 ---------- */
  const TOK_COLORS = {
    input: 'var(--ui-accent,#0969da)',   // 非缓存输入
    cache: '#2da44e',                    // 缓存命中
    output: '#bf8700',                   // 输出
  };

  /** 命中率 = 缓存读 / (非缓存输入 + 缓存读)。
   *  内核口径（providers/_telemetry.py）：input_tokens **不含**缓存命中，故分母要加回去。 */
  const hitRate = (t) => {
    const denom = (t.input || 0) + (t.cache || 0);
    return denom ? (t.cache || 0) / denom * 100 : 0;
  };

  function renderTok() {
    tokNumEl.textContent = fmtTok(sessTok.total);
    tokEl.title = 'token 用量详情（本次会话累计 ' + sessTok.total + '）';
    if (!tokPanelEl.hidden) renderTokPanel();   // 面板开着就实时跟着刷新
  }

  function renderTokPanel() {
    const t = sessTok;
    const rate = hitRate(t);
    const total = t.total || (t.input + t.cache + t.cacheWrite + t.output) || 1;
    const seg = (v) => Math.max(0, (v || 0) / total * 100).toFixed(1);
    const L = lastStats || {};
    const row = (label, val, tag) => '<div class="row"><span>' + label
      + (tag ? '<u>' + tag + '</u>' : '') + '</span><b>' + val + '</b></div>';

    tokPanelEl.innerHTML =
      /* ── 上层：总体可视化 ── */
      '<div class="cap">本次会话累计</div>'
      + '<div class="big">' + fmtTok(t.total) + '<em>tokens</em></div>'
      + '<div class="cap" style="margin-top:4px">缓存命中率<span class="rate">'
      + rate.toFixed(1) + '%</span></div>'
      + '<div class="stack">'
      + '<i style="width:' + seg(t.input) + '%;background:' + TOK_COLORS.input + '"></i>'
      + '<i style="width:' + seg(t.cache) + '%;background:' + TOK_COLORS.cache + '"></i>'
      + '<i style="width:' + seg(t.output) + '%;background:' + TOK_COLORS.output + '"></i>'
      + '</div>'
      + '<div class="legend">'
      + '<span><em style="background:' + TOK_COLORS.input + '"></em>输入 ' + fmtTok(t.input) + '</span>'
      + '<span><em style="background:' + TOK_COLORS.cache + '"></em>缓存命中 ' + fmtTok(t.cache) + '</span>'
      + '<span><em style="background:' + TOK_COLORS.output + '"></em>输出 ' + fmtTok(t.output) + '</span>'
      + '</div>'
      /* ── 下层：垂直排列的详细数据 ── */
      + '<div class="rows">'
      + row('首字延迟', L.ttfa_ms ? Math.round(L.ttfa_ms) + ' ms' : '-', '本轮')
      + row('输出速度', L.tps ? Number(L.tps).toFixed(1) + ' tok/s' : '-', '本轮')
      + row('输入 token', fmtTok(t.input))
      + row('输出 token', fmtTok(t.output))
      + row('缓存命中', fmtTok(t.cache))
      + (t.cacheWrite ? row('缓存写入', fmtTok(t.cacheWrite)) : '')
      + row('缓存命中率', rate.toFixed(1) + '%')
      + row('总使用 token', fmtTok(t.total))
      + row('耗时', L.total_ms ? (L.total_ms / 1000).toFixed(2) + ' s' : '-', '本轮')
      + '</div>';
  }

  /** 与附件预览同款：bottom 锚定 → 统一向上展开 */
  function placeTokPanel() {
    const r = tokEl.getBoundingClientRect();
    const pr = tokPanelEl.getBoundingClientRect();
    let bottom = window.innerHeight - r.top + 8;
    bottom = Math.min(bottom, Math.max(8, window.innerHeight - pr.height - 8));
    tokPanelEl.style.top = 'auto';
    tokPanelEl.style.bottom = Math.round(bottom) + 'px';
    const left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - pr.width - 8));
    tokPanelEl.style.left = Math.round(left) + 'px';
  }

  function openTokPanel() {
    renderTokPanel();
    tokPanelEl.hidden = false;
    tokEl.classList.add('on');
    tokEl.setAttribute('aria-expanded', 'true');
    placeTokPanel();
  }

  function closeTokPanel() {
    tokPanelEl.hidden = true;
    tokEl.classList.remove('on');
    tokEl.setAttribute('aria-expanded', 'false');
  }

  /* 两个明细面板互斥：开一个就关另一个，别叠在一起 */
  const toggleTokPanel = () => {
    if (tokPanelEl.hidden) { closeCtxPanel(); openTokPanel(); } else { closeTokPanel(); }
  };

  /** 读内核配置 → 刷新下拉 + 能力（决定附件策略）+ 上下文上限 + 信息栏 */
  async function refreshModelState() {
    try {
      const cfg = await getConfig();
      // 提示词字符数：供「上下文占用分布」里「提示词」一类做估算（见 ctxParts）。
      sysChars = (cfg && typeof cfg.system_prompt === 'string') ? cfg.system_prompt.length : 0;
      renderModelSelect(cfg);
      const pid = cfg && cfg.active_provider;
      const mid = cfg && cfg.active_model;
      if (!pid || !mid) {
        modelCaps = { known: false, canUpload: false, canTools: false, model: '', provider: '', ctx: 0 };
        renderInfo();
        return;
      }
      const p = (cfg.providers || []).filter((x) => x.id === pid)[0];
      const m = getMeta(pid, mid);
      const live = {
        ctx: m.ctx, capabilities: m.caps, ctxMax: m.info.ctxMax,
        parameterSize: m.info.parameterSize,
        quantization: m.info.quantization, family: m.info.family,
      };
      const feats = resolveFeatures(pid, mid, p && p.base_url, live);
      modelCaps = {
        known: true, canUpload: !!feats.files, canTools: !!feats.tools,
        model: mid, provider: pid,
        // 上下文上限：优先用「模型信息」里配的 ctx；没有就不显示分母
        ctx: Number(m.ctx) > 0 ? Number(m.ctx) : 0,
      };
    } catch (e) {
      modelCaps = { known: false, canUpload: false, canTools: false, model: '', provider: '', ctx: 0 };
    }
    renderInfo();
  }

  /** 附件发送策略（按需求矩阵）：
   *   可传文件 + 不可工具 → body（直接发文件本体）
   *   可传文件 + 可工具   → url （发文件地址）
   *   不可传文件 + 可工具 → url （让模型用工具去取）
   *   两者都不支持        → text（发后端抽取出的纯文本）
   *  能力未知时保守走 text —— 纯文本是唯一不依赖上游能力的通道。 */
  function sendStrategy() {
    const up = modelCaps.canUpload;
    const tools = modelCaps.canTools;
    if (up && !tools) return 'body';
    if (tools) return 'url';
    return 'text';
  }

  /** 把编辑区分段 + 附件信息，按当前策略拼成请求体 */
  function buildPayload() {
    const strat = sendStrategy();
    let content = '';
    const images = [];
    const docs = [];
    const tids = [];
    const pad = () => { if (content && !/\s$/.test(content)) content += ' '; };

    readSegments().forEach((s) => {
      if (s.type === 'text') { content += s.value; return; }
      const a = findAtt(s.tid);
      if (!a) return;
      tids.push(a.tid);
      if (strat === 'url') {
        pad();
        content += a.absUrl || a.url || a.name;
      } else if (strat === 'text') {
        const body = a.text || ('（无法抽取正文：' + (a.textError || '未知原因') + '）');
        content += '\n【附件：' + a.name + '】\n' + body + '\n【附件结束】\n';
      } else {                                   // body：正文只留文件名，本体走结构化字段
        pad();
        content += a.name;
        if (a.kind === 'image' && a.dataUri) images.push(a.dataUri);
        else if (a.dataUri) docs.push({ name: a.name, mime: a.mime, data: a.dataUri });
      }
    });
    return { content: content.trim(), images: images, docs: docs, strategy: strat, tids: tids };
  }

  /**
   * 追加一条消息。
   * 全程用 createElement + textContent，不用 innerHTML ——
   * 消息内容来自用户输入，拼 HTML 会有 XSS 风险。
   */
  function addMessage({ me = false, name = '', text = '', ts = Date.now(), files = null } = {}) {
    const row = document.createElement('div');
    row.className = 'c-row' + (me ? ' me' : '');

    const avatar = document.createElement('div');
    avatar.className = 'c-avatar';
    avatar.textContent = me ? '我' : (name ? name.slice(0, 1) : 'AI');
    avatar.setAttribute('aria-hidden', 'true');

    const body = document.createElement('div');
    body.className = 'c-body';

    const meta = document.createElement('div');
    meta.className = 'c-meta';
    if (name) {
      const n = document.createElement('span');
      n.className = 'c-name';
      n.textContent = name;
      meta.appendChild(n);
    }
    const t = document.createElement('span');
    t.className = 'c-time';
    t.textContent = hhmm(ts);
    meta.appendChild(t);

    const bubble = document.createElement('div');
    bubble.className = 'c-bubble';

    if (me) {
      // 用户消息：保持纯文本 + 原始蓝色气泡，不走 Markdown（输入通常是自然语言）
      bubble.textContent = text;
    } else {
      // 助手消息：直接 Markdown 渲染到气泡内（DOMPurify 已消毒，安全）
      // 注意：流式回复时 addMessage 只建空气泡，真正的 render 日志在 respond() 收尾时记一次
      const html = renderMd(text);
      if (html != null) {
        bubble.innerHTML = html;
        highlightCode(bubble);            // 代码块加 hljs 高亮
      } else {
        bubble.textContent = text;         // 解析器不可用时的回退
      }
    }

    body.appendChild(meta);
    body.appendChild(bubble);
    // 用户消息带的附件：在正文下方列出文件名（textContent，无注入面）
    if (me && files && files.length) {
      const atts = document.createElement('div');
      atts.className = 'c-atts';
      atts.textContent = '附件：' + files.map((f) => f.name).join('、');
      body.appendChild(atts);
    }
    row.appendChild(avatar);
    row.appendChild(body);
    innerEl.appendChild(row);

    syncEmpty();
    scrollToEnd();
    return { row, bubble, body };
  }

  /** 「正在输入」指示器，返回移除函数 */
  function addTyping() {
    const row = document.createElement('div');
    row.className = 'c-row';

    const avatar = document.createElement('div');
    avatar.className = 'c-avatar';
    avatar.textContent = 'AI';

    const body = document.createElement('div');
    body.className = 'c-body';
    const bubble = document.createElement('div');
    bubble.className = 'c-bubble';
    const dots = document.createElement('div');
    dots.className = 'c-typing';
    dots.innerHTML = '<i></i><i></i><i></i>';   // 纯装饰，无用户数据
    bubble.appendChild(dots);
    body.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(body);
    innerEl.appendChild(row);
    scrollToEnd();

    return () => row.remove();
  }

  function scrollToEnd() {
    if (!chatPrefs.autoScroll) return;   // 关闭自动滚动：保留用户当前位置
    // 等布局完成后再滚，否则拿到的是旧高度
    requestAnimationFrame(() => {
      listEl.scrollTop = listEl.scrollHeight;
    });
  }

  /* ---------- 发送 ---------- */
  function clearComposer() {
    inputEl.innerHTML = '';
    attachments = [];
    hidePreview();
    syncPlaceholder();
    autoGrow();
    syncSend();
  }

  function send() {
    if (busy) return;
    const payload = buildPayload();
    if (!payload.content && !payload.images.length && !payload.docs.length) return;

    const used = attachments.filter((a) => payload.tids.indexOf(a.tid) >= 0);
    addMessage({ me: true, text: payload.content, files: used.map((a) => ({ name: a.name, size: a.size })) });
    // 记入历史字符数：供「上下文占用分布」里「历史记录」一类做估算（见 ctxParts）。
    msgs.push({ role: 'user', chars: payload.content.length });
    // 真实记录：用户从前端发出指令 → 进入核心处理器（输入管道）
    log.info({ source: 'fe', target: 'cpu', type: 'control',
               payload: { len: payload.content.length, files: used.length, strategy: payload.strategy } });
    clearComposer();

    // 记下清理句柄：切页/销毁时要把未完成的回复定时器取消掉，
    // 否则用户已经离开本页，助手回复还会在后面悄悄冒出来。
    cancelReply = respond(payload);
  }

  /**
   * 生成回复：调用 P.A.L.M 对话后端（SSE 流式）。
   *
   * 事件契约（见后端 palm_llm/server/chat.py）：
   *   meta      → 会话 id / 标题（首尾各一次，尾部带 finished:true）
   *   reasoning → 思维链增量（本页暂不展示）
   *   token     → 正文增量（增量渲染 Markdown）
   *   done      → 用量 / 统计
   *   error     → 错误（error_type / retryable / request_id）
   *   以 `data: [DONE]` 收尾
   *
   * 返回清理函数（切页 / destroy 时中断请求）。
   */
  function respond(payload) {
    busy = true;
    syncSend();
    const removeTyping = addTyping();

    const controller = new AbortController();
    let acc = '';                // 累积正文
    let bubble = null;           // 助手气泡（首个 token 时创建）
    let statsBody = null;        // 助手消息 body（回合统计挂这里）
    let turnStats = null;        // done 事件回传的归一统计（TurnStats，见后端 _telemetry.py）
    const tSend = Date.now();    // 请求时间（前端视角，回填到统计行）
    let firstToken = true;
    let flushTimer = 0;

    const ensureBubble = () => {
      if (!bubble) {
        const m = addMessage({ name: '助手', text: '' });
        bubble = m.bubble;
        statsBody = m.body;
      }
      return bubble;
    };
    const flush = () => {
      flushTimer = 0;
      if (!bubble) return;
      const html = renderMd(acc);
      if (html != null) { bubble.innerHTML = html; highlightCode(bubble); }
      else { bubble.textContent = acc; }
      scrollToEnd();
    };
    const scheduleFlush = () => { if (!flushTimer) flushTimer = setTimeout(flush, 80); };

    /** 回合统计：Token 行 + 详情行，textContent 写入（后端数值，无注入面）。
     *  可见性由根元素 no-tok / no-detail 类控制（设置页开关实时生效）。 */
    function attachTurnStats() {
      if (!turnStats || !statsBody) return;
      const wrap = document.createElement('div');
      wrap.className = 'c-stats';
      const tok = document.createElement('div');
      tok.className = 'c-stats-tok';
      tok.textContent = 'Token 输入 ' + (turnStats.input_tokens || 0)
        + ' · 缓存命中 ' + (turnStats.cache_read_tokens || 0)
        + ' · 输出 ' + (turnStats.output_tokens || 0)
        + ' · 总计 ' + (turnStats.total_tokens || 0);
      const det = document.createElement('div');
      det.className = 'c-stats-detail';
      // 流式路径下请求 ID 在 stats.extra.response_id（见后端 _meta_extra），顶层字段仅非流式有值
      const reqId = turnStats.response_id || (turnStats.extra && turnStats.extra.response_id) || '-';
      det.textContent = '首字 ' + (turnStats.ttfa_ms ? Math.round(turnStats.ttfa_ms) + 'ms' : '-')
        + ' · 速度 ' + (turnStats.tps || 0) + ' tok/s'
        + ' · 耗时 ' + (turnStats.total_ms ? Math.round(turnStats.total_ms) + 'ms' : '-')
        + ' · 请求ID ' + reqId
        + ' · ' + hhmmss(tSend);
      wrap.appendChild(tok);
      wrap.appendChild(det);
      statsBody.appendChild(wrap);
    }

    (async () => {
      try {
        const body = { content: payload.content, conversation_id: conversationId || undefined };
        /* 附件：走「发本体」策略时才带结构化字段。
             图片 → images（List[str]，data URI）；其余 → files（{name,mime,data}）。
           走「发地址 / 发纯文本」策略时，内容已经内联进 content，这里不带，
           否则内核会把 /uploads 路径读成 data URI，等于又发了一遍本体。 */
        if (payload.images && payload.images.length) body.images = payload.images;
        if (payload.docs && payload.docs.length) body.files = payload.docs;
        const res = await fetch(CHAT_API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);

        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const raw = buf.slice(0, i); buf = buf.slice(i + 2);
            const line = raw.replace(/^data:\s?/, '').trim();
            if (!line || line === '[DONE]') continue;
            let ev; try { ev = JSON.parse(line); } catch { continue; }
            if (ev.type === 'meta') {
              if (ev.conversation_id) conversationId = ev.conversation_id;
            } else if (ev.type === 'token') {
              if (firstToken) { removeTyping(); firstToken = false; ensureBubble(); }
              acc += ev.content || '';
              scheduleFlush();
            } else if (ev.type === 'done') {
              turnStats = ev.stats || null;   // provider 未回传统计时则为 null，前端降级不显示
              if (turnStats) {
                sessTok.input += turnStats.input_tokens || 0;
                sessTok.cache += turnStats.cache_read_tokens || 0;
                sessTok.cacheWrite += turnStats.cache_write_tokens || 0;
                sessTok.output += turnStats.output_tokens || 0;
                sessTok.total += turnStats.total_tokens || 0;
                lastStats = turnStats;
                renderInfo();                 // 信息栏：上下文占用
                renderTok();                  // token 卡片：总用量 + 明细面板
              }
            } else if (ev.type === 'error') {
              throw new Error(ev.message || '后端错误');
            }
          }
        }
        if (flushTimer) { clearTimeout(flushTimer); flushTimer = 0; }
        if (firstToken) { removeTyping(); firstToken = false; ensureBubble(); }
        flush();
        attachTurnStats();
        // 记入助手回复字符数：历史记录估算 += 本轮输出（见 ctxParts）。
        msgs.push({ role: 'assistant', chars: acc.length });
        // 真实记录：渲染器确实渲染了内容（处理器产出 → 前端，输出管道）
        log.info({ source: 'cpu', target: 'fe', type: 'render' });
      } catch (err) {
        if (err && err.name === 'AbortError') return;   // 主动取消，静默
        removeTyping();
        ensureBubble();
        acc += (acc ? '\n\n' : '')
          + '> ⚠️ 无法连接对话后端（`' + CHAT_API + '`）：' + (err.message || err)
          + '\n>\n> 请先启动后端：`python -m palm_llm.server.api`（端口 10093）';
        flush();
      } finally {
        busy = false;
        cancelReply = null;          // 已完结，句柄失效
        syncSend();
      }
    })();

    // 切页 / destroy 时：中断请求 + 清定时器 + 收掉打字指示
    return () => { controller.abort(); if (flushTimer) clearTimeout(flushTimer); removeTyping(); };
  }

  /** 输入区自适应高度（contenteditable：直接量 scrollHeight 即可）。
   *
   *  ⚠️ 不要用「先置 height:auto 再读 scrollHeight」的老写法：超长文本（10w+ 字，
   *  内容高两万多 px）时，每次输入都会让元素瞬间展开成全高再收回来，白白付一次
   *  整篇重排，还会让滚动位置抖动。scrollHeight 本来就等于内容全高，直接夹取即可。 */
  function autoGrow() {
    const h = Math.min(inputEl.scrollHeight, MAX_INPUT_H);
    const px = h + 'px';
    if (inputEl.style.height !== px) inputEl.style.height = px;
  }

  /* ---------- 事件 ---------- */

  const onInput = () => {
    autoGrow();
    syncPlaceholder();
    syncSend();
  };

  const onKeydown = (e) => {
    // Enter 发送（Shift+Enter 换行）；输入法组合中的 Enter 不拦截
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      if (!chatPrefs.enterSend) return;   // 关闭回车发送：Enter 仅换行
      e.preventDefault();
      send();
    }
  };

  const onPaste = (e) => {
    // 只吃纯文本：免得把网页的样式 / 图片粘进来污染编辑区与分段逻辑
    e.preventDefault();
    const t = (e.clipboardData || window.clipboardData).getData('text/plain') || '';
    if (t) document.execCommand('insertText', false, t);
  };

  /* 悬停预览：进入卡片显示，移出即隐藏 */
  const onOver = (e) => {
    const tok = e.target && e.target.closest ? e.target.closest('.c-token') : null;
    if (!tok) { if (hoverTid) hidePreview(); return; }
    if (tok.dataset.tid === hoverTid) return;
    hoverTid = tok.dataset.tid;
    showPreview(tok, findAtt(hoverTid));
  };

  const onClick = (e) => {
    if (e.target.closest('[data-send]')) { send(); return; }
    if (e.target.closest('[data-upload]')) { fileInput.click(); return; }
    if (e.target.closest('[data-tok]')) { toggleTokPanel(); return; }
    if (e.target.closest('[data-ctxbtn]')) { toggleCtxPanel(); return; }
    const rm = e.target.closest('[data-rm]');
    if (rm) { removeAttachment(rm.dataset.rm); return; }
  };

  const onModelChange = () => switchModel(modelSel.value);

  /* 两个明细面板：点外面 / Esc / 滚动 都收起来 */
  const onDocClick = (e) => {
    if (tokPanelEl.hidden && ctxPanelEl.hidden) return;
    if (e.target.closest('[data-tok]') || e.target.closest('[data-tokpanel]')
        || e.target.closest('[data-ctxbtn]') || e.target.closest('[data-ctxpanel]')) return;
    closePanels();
  };
  const onDocKey = (e) => {
    if (e.key === 'Escape' && (!tokPanelEl.hidden || !ctxPanelEl.hidden)) closePanels();
  };
  const onWinResize = () => {
    if (!tokPanelEl.hidden) placeTokPanel();
    if (!ctxPanelEl.hidden) placeCtxPanel();
  };

  const onFilePick = () => {
    pickFiles(fileInput.files);
    fileInput.value = '';          // 清空，允许连续选同一个文件
  };

  inputEl.addEventListener('input', onInput);
  inputEl.addEventListener('keydown', onKeydown);
  inputEl.addEventListener('paste', onPaste);
  inputEl.addEventListener('mouseover', onOver);
  inputEl.addEventListener('mouseleave', hidePreview);
  listEl.addEventListener('scroll', hidePreview);
  host.addEventListener('click', onClick);
  fileInput.addEventListener('change', onFilePick);
  modelSel.addEventListener('change', onModelChange);
  document.addEventListener('click', onDocClick);
  document.addEventListener('keydown', onDocKey);
  window.addEventListener('resize', onWinResize);
  listEl.addEventListener('scroll', closePanels);

  /* ---------- 聊天行为偏好：实时订阅设置页变更 ---------- */
  function applyPrefClasses() {
    rootEl.classList.toggle('no-time', !chatPrefs.showTime);
    rootEl.classList.toggle('no-tok', !chatPrefs.showTokenStats);
    rootEl.classList.toggle('no-detail', !chatPrefs.showDetailInfo);
  }
  function refreshChatPrefs() {
    for (const k of Object.keys(chatPrefs)) chatPrefs[k] = readChatPref(k, true);
    applyPrefClasses();
  }
  function onChatPref(e) {
    const d = e.detail || {};
    if (!(d.key in chatPrefs)) return;
    chatPrefs[d.key] = !!d.val;
    applyPrefClasses();
  }
  window.addEventListener('webui:chat-pref', onChatPref);
  refreshChatPrefs();   // 挂载时重读存储：补上未挂载期间错过的设置变更

  /* 模型状态：下拉列表 + 附件发送策略（取决于当前模型能力）+ 上下文上限 + 信息栏。
     挂载时读一次；切回本页时再刷（设置页可能换过模型）。 */
  refreshModelState();
  renderTok();

  // Markdown 渲染结果直接挂在 bubble.innerHTML 上，主题切换只需让
  // CSS 变量改一改就能换色，不需要逐个元素回调。
  syncPlaceholder();
  autoGrow();
  syncEmpty();
  syncSend();

  return {
    onShow() {
      // 切回本页时把焦点还给输入框，省一次点击
      requestAnimationFrame(() => inputEl.focus());
      scrollToEnd();
      refreshModelState();
    },
    onHide() {
      // 刻意不取消回复：框架是「隐藏保留状态」，用户切走再回来时
      // 回复应该已经就位，像正常聊天软件那样。
      // 只有真正销毁（unmount）时才需要清理定时器。
      hidePreview();
    },
    destroy() {
      if (cancelReply) { cancelReply(); cancelReply = null; }
      busy = false;
      inputEl.removeEventListener('input', onInput);
      inputEl.removeEventListener('keydown', onKeydown);
      inputEl.removeEventListener('paste', onPaste);
      inputEl.removeEventListener('mouseover', onOver);
      inputEl.removeEventListener('mouseleave', hidePreview);
      listEl.removeEventListener('scroll', hidePreview);
      host.removeEventListener('click', onClick);
      fileInput.removeEventListener('change', onFilePick);
      modelSel.removeEventListener('change', onModelChange);
      document.removeEventListener('click', onDocClick);
      document.removeEventListener('keydown', onDocKey);
      window.removeEventListener('resize', onWinResize);
      listEl.removeEventListener('scroll', closePanels);
      window.removeEventListener('webui:chat-pref', onChatPref);
      attachments = [];
      host.innerHTML = '';
    },
  };
}
