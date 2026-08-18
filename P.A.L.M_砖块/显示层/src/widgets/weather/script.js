// ===== 天气组件 =====
// 纯后端驱动：PALM.on("weather") 接收后端统一采集的天气数据
// 无数据时各字段显示 N/O
const WMO = {
  0:["晴","☀️"],1:["大致晴朗","🌤️"],2:["局部多云","⛅"],3:["阴","☁️"],
  45:["雾","🌫️"],48:["雾凇","🌫️"],51:["毛毛雨","🌦️"],53:["小雨","🌧️"],55:["中雨","🌧️"],
  61:["小雨","🌧️"],63:["中雨","🌧️"],65:["大雨","🌧️"],71:["小雪","🌨️"],73:["中雪","❄️"],75:["大雪","❄️"],
  80:["阵雨","🌦️"],81:["阵雨","🌦️"],82:["强阵雨","⛈️"],95:["雷阵雨","⛈️"],96:["雷阵雨伴冰雹","⛈️"]
};
function wmo(code){ return WMO[code] || ["未知","🌡️"]; }

function paint(d){
  document.getElementById("temp").textContent = Math.round(d.t);
  const pair = wmo(d.code);
  document.getElementById("icon").textContent = pair[1];
  document.getElementById("desc").textContent = pair[0];
  document.getElementById("city").textContent = d.city;
  document.getElementById("sub").textContent = Math.round(d.wind) + " km/h";
  document.getElementById("hum").textContent = (d.hum != null ? Math.round(d.hum) : "--") + "%";
  document.getElementById("feels").textContent = (d.feels != null ? Math.round(d.feels) : "--") + "°";
}

function showNoData(){
  document.getElementById("temp").textContent = "--";
  document.getElementById("icon").textContent = "❓";
  document.getElementById("desc").textContent = "N/O";
  document.getElementById("city").textContent = "N/O";
  document.getElementById("sub").textContent = "-- km/h";
  document.getElementById("hum").textContent = "--%";
  document.getElementById("feels").textContent = "--°";
}

// 订阅后端 weather provider（值变化时推送）
PALM.on("weather", data => {
  if (data) paint(data);
  else showNoData();
});

// 初始取一次快照
PALM.providers.get("weather").then(data => {
  if (data) paint(data);
  else showNoData();
}).catch(() => {
  showNoData();
});
