// ===== 自定义区 =====
const WEEK_START = 0; // 0=周日开头，1=周一开头
// ====================

function build(){
  const now = new Date();
  const y = now.getFullYear(), mo = now.getMonth();
  document.getElementById("ym").textContent = y + "年" + (mo + 1) + "月";
  const today = now.getDate();
  const first = new Date(y, mo, 1);
  const startOffset = (first.getDay() - WEEK_START + 7) % 7;
  const daysInMonth = new Date(y, mo + 1, 0).getDate();
  const cells = [];
  for(let i = 0; i < startOffset; i++) cells.push('<div class="cell dim"></div>');
  for(let d = 1; d <= daysInMonth; d++){
    const cls = (d === today) ? "cell today" : "cell";
    cells.push('<div class="' + cls + '">' + d + "</div>");
  }
  document.getElementById("grid").innerHTML = cells.join("");
  document.getElementById("today").textContent = (mo + 1) + "月" + today + "日";
}

build();
// 每分钟刷新一次（跨午夜自动翻页）；引擎推送的 time 字段未被本组件使用，仅作触发信号
PALM.onTick(60000, build);
