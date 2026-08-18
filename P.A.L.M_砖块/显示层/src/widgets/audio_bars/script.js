// ===== 音频律动条 =====
// 纯后端驱动：PALM.on("audio") 接收后端扬声器回环采集的频谱数据
// 无数据时显示 N/O
const BAR_COUNT = 24;
const barsEl = document.getElementById("bars");
const noData = document.getElementById("noData");

// --- 创建条形元素 ---
const bars = [];
for (let i = 0; i < BAR_COUNT; i++){
  const el = document.createElement("div");
  el.className = "bar";
  el.style.height = "3px";
  barsEl.appendChild(el);
  bars.push(el);
}

function updateBars(data){
  if (!data || !data.bars){
    noData.style.display = "flex";
    barsEl.style.display = "none";
    return;
  }
  noData.style.display = "none";
  barsEl.style.display = "flex";
  const arr = data.bars;
  for (let i = 0; i < BAR_COUNT; i++){
    const v = arr[i] || 0;
    bars[i].style.height = Math.max(3, v) + "%";
  }
}

// 订阅后端 audio provider（值变化时推送，~30fps）
PALM.on("audio", data => {
  if (data) updateBars(data);
});

// 初始取一次快照
PALM.providers.get("audio").then(data => {
  updateBars(data);
}).catch(() => {
  noData.style.display = "flex";
  barsEl.style.display = "none";
});
