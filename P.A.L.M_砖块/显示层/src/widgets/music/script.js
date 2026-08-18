// ===== 自定义区：把你的歌单填进来（dur 为秒） =====
const PLAYLIST = [
  {title:"夜空中最亮的星", artist:"逃跑计划", dur:252, color:"#34d399"},
  {title:"晴天",           artist:"周杰伦",   dur:269, color:"#0ea5e9"},
  {title:"稻香",           artist:"周杰伦",   dur:223, color:"#f59e0b"},
  {title:"起风了",         artist:"买辣椒也用券", dur:325, color:"#a78bfa"}
];
// =============================================
let idx = 0, playing = true, pos = 0, timer = null;
const $ = id => document.getElementById(id);
function fmt(s){ s = Math.max(0, Math.floor(s)); return Math.floor(s/60) + ":" + String(s%60).padStart(2,"0"); }
function render(){
  const t = PLAYLIST[idx];
  $("title").textContent = t.title;
  $("artist").textContent = t.artist;
  $("cover").style.background = "linear-gradient(135deg," + t.color + ",#0ea5e9)";
  $("cover").classList.toggle("playing", playing);
  $("dur").textContent = fmt(t.dur);
  $("cur").textContent = fmt(pos);
  $("fill").style.width = (pos / t.dur * 100) + "%";
  $("play").textContent = playing ? "⏸" : "▶";
}
function tick(){
  const t = PLAYLIST[idx];
  pos += 1;
  if(pos >= t.dur){ pos = 0; idx = (idx + 1) % PLAYLIST.length; }
  render();
}
function start(){ stop(); timer = setInterval(tick, 1000); }
function stop(){ if(timer) clearInterval(timer); timer = null; }
$("prev").onclick = () => { idx = (idx - 1 + PLAYLIST.length) % PLAYLIST.length; pos = 0; render(); };
$("next").onclick = () => { idx = (idx + 1) % PLAYLIST.length; pos = 0; render(); };
$("play").onclick = () => { playing = !playing; if(playing) start(); else stop(); render(); };
render();
if(playing) start();
