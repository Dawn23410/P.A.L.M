// ===== 自定义区 =====
const USE_24H = true; // 改成 false 用 12 小时制（带 AM/PM）
const WD = {Monday:"周一",Tuesday:"周二",Wednesday:"周三",Thursday:"周四",Friday:"周五",Saturday:"周六",Sunday:"周日"};
// ====================

function render(t){
  let h = t.hour, m = t.minute, s = t.second;
  let ap = "";
  if(!USE_24H){ ap = h < 12 ? " AM" : " PM"; h = h % 12; if(h === 0) h = 12; }
  const pad = n => String(n).padStart(2,"0");
  document.getElementById("hhmm").textContent = pad(h) + ":" + pad(m);
  document.getElementById("ss").textContent = pad(s);
  document.getElementById("date").textContent = t.date.replace(/-/g,"/");
  document.getElementById("wd").textContent = (WD[t.weekday] || t.weekday) + ap;
}

// 引擎每秒推送一次（仅本组件声明的 time 字段），直接渲染
PALM.onTick(1000, snap => { if(snap && snap.time) render(snap.time); });
