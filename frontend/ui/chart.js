/* 图表组件：Canvas 迷你折线/柱状（零依赖），界面复用。 */

/** 折线图：values 数组 → 绘制到 canvas（含网格与最大值标注）。 */
export function lineChart(canvas, values, { color = "#6ee7a8", fill = true } = {}) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!values || values.length < 2) return;
  const max = Math.max(...values, 1);
  const step = w / (values.length - 1);
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = i * step;
    const y = h - (v / max) * (h - 8) - 4;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  if (fill) {
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle = color + "22";
    ctx.fill();
  }
}

/** 柱状图：labels+values → 横向柱状（适合用量/排名类展示）。 */
export function barChart(canvas, labels, values, { color = "#7fb0ff" } = {}) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!labels?.length) return;
  const max = Math.max(...values, 1);
  const row = h / labels.length;
  ctx.font = "11px sans-serif";
  ctx.fillStyle = "#8b929c";
  ctx.textBaseline = "middle";
  labels.forEach((label, i) => {
    const bw = (values[i] / max) * (w - 90);
    ctx.fillStyle = color;
    ctx.fillRect(80, i * row + row * 0.25, bw, row * 0.5);
    ctx.fillStyle = "#8b929c";
    ctx.fillText(String(label), 2, i * row + row * 0.5);
    ctx.fillStyle = "#e6e8eb";
    ctx.fillText(String(values[i]), 82 + bw, i * row + row * 0.5);
  });
}
