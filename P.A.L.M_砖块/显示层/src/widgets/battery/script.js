// 电池圆环：订阅引擎的 battery 推送（已修复），并首帧主动取一次
const R = 42, C = 2 * Math.PI * R; // 圆环周长 ≈ 263.9
const $ = id => document.getElementById(id);
function paint(b){
  if(!b) return;
  const p = Math.max(0, Math.min(100, b.percent));
  $("pct").textContent = Math.round(p);
  $("fg").style.strokeDashoffset = C * (1 - p / 100);
  // 充电绿、低电红、一般黄绿
  const color = b.plugged ? "#4ade80" : (p < 20 ? "#f87171" : (p < 50 ? "#fbbf24" : "#4ade80"));
  $("fg").style.stroke = color;
  document.documentElement.style.setProperty("--accent", color);
  $("state").textContent = b.plugged ? "⚡ 充电中" : (p < 20 ? "电量偏低" : "放电中");
}

PALM.on("battery", paint);
PALM.providers.get("battery").then(paint).catch(() => {});
