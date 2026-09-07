# -*- coding: utf-8 -*-
"""轻量工具调用层（零依赖、fail-closed）。

提供确定性结构化信息回复：时间 / 日期 / 天气。
设计原则（与 P.A.L.M 既有的 fail-closed / 零幻觉一致）：
- 时间 / 日期：网络授时平台优先（worldtimeapi），没网 / 超时 → 直接读取本机时间，
  绝不因取不到授时而失败（fail-closed）；data 带 source 字段诚实披露来源。
- 天气：open-meteo 免费无密钥 API（标准库 urllib），结果按「城市+日期」做 TTL 预缓存
  （默认 30 分钟，宿主可 prefetch 预热常用城市）；网络失败 / 超时 → 先读陈旧缓存兜底，
  无任何缓存才诚实降级，绝不编造温度或假装联网成功；未知城市 → 默认北京并明示。
- 工具命中优先于检索缝合：用户要"现在几点 / 今天几号 / 北京天气"这类结构化信息，
  引擎应给出**精确**答案而非检索近似句（检索句里没有真实时间）。
- 所有输出经人格化封装（猫娘语气），保持人设锁一致。
"""
import re
import json
import time
import urllib.request
import datetime

# ── 城市坐标表（常见城市，度分秒已转十进制；未知城市回退北京）──
_CITY_COORDS = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551), "成都": (30.5728, 104.0668),
    "武汉": (30.5928, 114.3055), "南京": (32.0603, 118.7969),
    "西安": (34.3416, 108.9398), "重庆": (29.5630, 106.5516),
    "苏州": (31.2989, 120.5853), "天津": (39.0842, 117.2009),
    "长沙": (28.2282, 112.9388), "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894), "郑州": (34.7466, 113.6254),
    "昆明": (24.8801, 102.8329), "大连": (38.9140, 121.6147),
    "宁波": (29.8683, 121.5440), "哈尔滨": (45.8038, 126.5349),
    "沈阳": (41.8057, 123.4315), "济南": (36.6512, 117.1201),
    "福州": (26.0745, 119.2965), "合肥": (31.8206, 117.2272),
    "南昌": (28.6829, 115.8579), "贵阳": (26.6470, 106.6302),
    "南宁": (22.8170, 108.3665), "兰州": (36.0611, 103.8343),
    "太原": (37.8706, 112.5489), "石家庄": (38.0428, 114.5149),
    "乌鲁木齐": (43.8256, 87.6168), "拉萨": (29.6520, 91.1721),
    "呼和浩特": (40.8426, 111.7519), "银川": (38.4872, 106.2309),
    "西宁": (36.6171, 101.7782), "海口": (20.0444, 110.1989),
    "三亚": (18.2528, 109.5119), "桂林": (25.2736, 110.2900),
    "香港": (22.3193, 114.1694), "台北": (25.0330, 121.5654),
}
_DEFAULT_CITY = "北京"

# 常见国际城市（扩展覆盖，open-meteo 全球可用）
_CITY_COORDS.update({
    "纽约": (40.7128, -74.0060), "伦敦": (51.5074, -0.1278),
    "东京": (35.6762, 139.6503), "巴黎": (48.8566, 2.3522),
    "洛杉矶": (34.0522, -118.2437), "旧金山": (37.7749, -122.4194),
    "新加坡": (1.3521, 103.8198), "首尔": (37.5665, 126.9780),
    "莫斯科": (55.7558, 37.6173), "悉尼": (-33.8688, 151.2093),
    "多伦多": (43.6532, -79.3832), "柏林": (52.5200, 13.4050),
    "迪拜": (25.2048, 55.2708), "曼谷": (13.7563, 100.5018),
    "温哥华": (49.2827, -123.1207), "芝加哥": (41.8781, -87.6298),
})

# open-meteo WMO 天气代码 → 中文描述
_WEATHER_DESC = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴小雹", 99: "雷阵雨伴大雹",
}
_WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 日期偏移词 → open-meteo daily 数组下标
_DAY_OFFSET = {"今天": 0, "现在": 0, "此刻": 0, "明天": 1, "后天": 2}
_DAY_LABEL = {0: "今天", 1: "明天", 2: "后天"}


# ── 网络授时（fail-closed：多授时源冗余，全失败/超时直接本机）──
# 主源 worldtimeapi；兜底源用可靠主机的 HTTP `Date` 响应头（RFC1123 格式），
# 任一可达即取到网络时间。全部不可达 → 返回 None，由 _now 兜底本机。
_TIME_SOURCES = [
    "http://worldtimeapi.org/api/timezone/Asia/Shanghai",
    "https://www.baidu.com",          # Date 响应头含 GMT 服务器时间
    "https://api.github.com",          # 同上
]


def _parse_date_header(raw):
    """解析 HTTP Date 头（如 'Sun, 06 Sep 2026 11:09:00 GMT'）→ 本地时区 datetime。"""
    try:
        import email.utils as _eu
        dt = _eu.parsedate_to_datetime(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt
    except Exception:
        return None


def _fetch_network_now():
    """尝试多个授时平台拿精确时间；任意失败返回 None，由 _now 兜底本机。"""
    for url in _TIME_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "palm-mock/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if "worldtimeapi.org" in url:
                    payload = json.loads(resp.read().decode("utf-8"))
                    iso = payload.get("datetime")
                    if iso:
                        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
                else:
                    date_hdr = resp.headers.get("Date")
                    if date_hdr:
                        dt = _parse_date_header(date_hdr)
                        if dt is not None:
                            return dt
        except Exception:
            continue
    return None


def _now():
    """网络授时优先；没网/失败直接读取本机时间。返回 (datetime, source)。"""
    nw = _fetch_network_now()
    if nw is not None:
        return nw, "network"
    return datetime.datetime.now(), "local"


class ToolResult:
    """工具执行结果。ok=False 表示工具未能成功（网络失败/未知等），由调用方降级。"""
    __slots__ = ("ok", "data", "error")

    def __init__(self, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


# ── 工具基类 ──
class Tool:
    name = "tool"

    def match(self, query):
        raise NotImplementedError

    def execute(self, query):
        raise NotImplementedError

    def format(self, result, query):
        """把 ToolResult 包成猫娘语气正文（仅正文，前缀由引擎统一加）。"""
        raise NotImplementedError


class TimeTool(Tool):
    name = "time"

    _PAT = re.compile(r"(现在|此刻|这[会刻]|当前).*(几[点刻]|分|时间)|几[点刻]了?$|现在什么时间|几点了")

    def match(self, query):
        return bool(self._PAT.search(query or "")) or "几点" in (query or "") or "现在时间" in (query or "")

    def execute(self, query):
        now, src = _now()
        return ToolResult(True, {
            "type": "time", "source": src,
            "hour": now.hour, "minute": now.minute, "second": now.second,
            "weekday": _WEEKDAY_CN[now.weekday()],
        })

    def format(self, result, query):
        d = result.data
        return "现在是{d[hour]:02d}点{d[minute]:02d}分啦，{d[weekday]}哦".format(d=d)


class DateTool(Tool):
    name = "date"

    _PAT = re.compile(r"(今天|现在|这[会天]).*(几号|日期|星期|周几|几月|农历)|日期|今天星期几|今天周几|几月几号|今天是")

    def match(self, query):
        q = query or ""
        if re.search(r"几号|日期|星期几|周几|几月几|今天是", q):
            return True
        if "今天" in q and ("星期" in q or "周" in q or "几号" in q or "几月" in q):
            return True
        return False

    def execute(self, query):
        now, src = _now()
        return ToolResult(True, {
            "type": "date", "source": src,
            "year": now.year, "month": now.month, "day": now.day,
            "weekday": _WEEKDAY_CN[now.weekday()],
        })

    def format(self, result, query):
        d = result.data
        return "今天是{d[year]}年{d[month]}月{d[day]}日，{d[weekday]}喵".format(d=d)


class WeatherTool(Tool):
    name = "weather"

    # 预缓存 TTL（秒）：天气短时变化小，30 分钟内重复查询直接读缓存，不重复联网。
    _TTL = 1800

    def __init__(self):
        self._cache = {}  # key=(city, offset) -> (timestamp, ToolResult)

    # 强意图词（避免误伤「天气真好呀」这类闲聊）：必须含疑问/请求形态或明确指标词。
    _STRONG = re.compile(
        r"气温|多少度|几度|温度|下雨吗|下雪吗|冷吗|热吗|冷不冷|热不冷|"
        r"天气预报|查天气|看天气|报一下?天气|问天气|查一下天气"
    )
    # WHY 不含裸"冷|热"：「今天好热/脚好冷」是体感闲聊不是查询（实测 + 日词
    # "今天" 被误判成天气查询，且冷热返回同一结果自相矛盾）。查询形态由
    # _STRONG（热吗/冷吗/几度…）与"天气/气温"指标词覆盖。
    _HAS_WEATHER = re.compile(r"天气|气温|温度|多少度|几度|下雨|下雪|湿度|风力|气象")
    _Q_MARK = re.compile(r"怎么|如何|怎样|吗|呢|啥|什么|情况")
    # 闲聊夸赞护栏：日期词+天气但属「天气真好/不错/美」这类陪伴闲聊，不触发工具。
    _PRAISE_WEATHER = re.compile(r"天气(真?好|不错|真棒|美|宜人|舒服|惬意|暖和|怡人|绝了)")

    def match(self, query):
        q = query or ""
        if self._STRONG.search(q):
            return True
        # 「天气」+ 疑问词（天气怎么样/天气如何）→ 工具意图；「天气真好」不命中。
        if "天气" in q and self._Q_MARK.search(q):
            return True
        # 「城市 + 天气/气温」即使无问号也视为查询（北京天气 / 上海气温）。
        if self._HAS_WEATHER.search(q) and self._find_city(q):
            return True
        # 「日期词 + 天气」即使无城市/问号也视为查询（明天天气 → 默认北京）。
        # 但「今天天气真好呀」属陪伴闲聊（带夸赞词），不触发工具，交给检索。
        if any(w in q for w in _DAY_OFFSET) and self._HAS_WEATHER.search(q):
            if not self._PRAISE_WEATHER.search(q):
                return True
        return False

    def _find_city(self, query):
        for city in _CITY_COORDS:
            if city in (query or ""):
                return city
        return None

    def _day_offset(self, query):
        for word, off in _DAY_OFFSET.items():
            if word in (query or ""):
                return off
        return 0

    def _cache_key(self, city, offset):
        return (city, offset)

    def execute(self, query):
        city = self._find_city(query) or _DEFAULT_CITY
        offset = self._day_offset(query)
        key = self._cache_key(city, offset)
        now_ts = time.time()
        # ① 新鲜缓存直接返回（秒回，不联网）
        if key in self._cache:
            ts, cached = self._cache[key]
            if now_ts - ts < self._TTL:
                return cached
        # ② 联网获取
        result = self._fetch(city, offset, query)
        if result.ok:
            self._cache[key] = (now_ts, result)
            return result
        # ③ 联网失败 → 陈旧缓存兜底（天气短时变化小，可接受）；无缓存才降级
        if key in self._cache:
            stale = self._cache[key][1]
            d = dict(stale.data)
            d["stale"] = True
            return ToolResult(True, d)
        return result

    def _fetch(self, city, offset, query):
        lat, lon = _CITY_COORDS[city]
        if offset == 0:
            url = ("https://api.open-meteo.com/v1/forecast?latitude={:.4f}&longitude={:.4f}"
                   "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                   "&timezone=auto").format(lat, lon)
        else:
            url = ("https://api.open-meteo.com/v1/forecast?latitude={:.4f}&longitude={:.4f}"
                   "&daily=weather_code,temperature_2m_max,temperature_2m_min"
                   "&forecast_days=3&timezone=auto").format(lat, lon)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "palm-mock/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if offset == 0:
                cur = payload["current"]
                code = int(cur.get("weather_code", 0))
                return ToolResult(True, {
                    "type": "weather",
                    "city": city, "day_label": "今天",
                    "temp": round(float(cur.get("temperature_2m", 0)), 1),
                    "humidity": int(cur.get("relative_humidity_2m", 0)),
                    "wind": round(float(cur.get("wind_speed_10m", 0)), 1),
                    "desc": _WEATHER_DESC.get(code, "未知"),
                    "defaulted": self._find_city(query) is None,
                })
            daily = payload["daily"]
            idx = min(offset, len(daily["weather_code"]) - 1)
            code = int(daily["weather_code"][idx])
            tmax = round(float(daily["temperature_2m_max"][idx]), 1)
            tmin = round(float(daily["temperature_2m_min"][idx]), 1)
            return ToolResult(True, {
                "type": "weather",
                "city": city, "day_label": _DAY_LABEL.get(offset, "今天"),
                "temp": tmax, "tmin": tmin, "tmax": tmax,
                "desc": _WEATHER_DESC.get(code, "未知"),
                "defaulted": self._find_city(query) is None,
            })
        except Exception as e:  # 网络失败 / 超时 / 解析异常 → fail-closed
            return ToolResult(False, error=str(e)[:80])

    def prefetch(self, cities=None, days=(0, 1, 2)):
        """宿主空闲时预热常用城市天气进缓存（fail-closed 不抛）。"""
        cities = cities or [_DEFAULT_CITY]
        for c in cities:
            if c not in _CITY_COORDS:
                continue
            for off in days:
                self.execute(f"{c}{_DAY_LABEL.get(off, '今天')}天气")

    def format(self, result, query):
        if not result.ok:
            return "呜…我这会儿连不上网查天气，怕给你瞎编温度。你换个时候再问，或者问点别的喵？"
        d = result.data
        note = "（没说哪个城市，我默认翻了北京的哦）" if d.get("defaulted") else ""
        stale_note = "（这是刚才缓存的，可能有点偏差喵）" if d.get("stale") else ""
        label = d.get("day_label", "今天")
        if "tmin" in d:  # 预报日：给温度区间
            return "{d[city]}{label}{d[desc]}，气温{d[tmin]}到{d[tmax]}度{note}{stale_note}".format(
                d=d, label=label, note=note, stale_note=stale_note)
        return "{d[city]}{label}{d[desc]}，气温{d[temp]}度，湿度{d[humidity]}%，风{d[wind]}米每秒{note}{stale_note}".format(
            d=d, label=label, note=note, stale_note=stale_note)


class ToolRegistry:
    """工具注册表：dispatch 返回首个匹配工具的 ToolResult；无匹配返回 None。"""

    def __init__(self):
        self.tools = [TimeTool(), DateTool(), WeatherTool()]

    def dispatch(self, query):
        for t in self.tools:
            if t.match(query):
                return t.execute(query), t
        return None

    def format(self, result, tool, query):
        return tool.format(result, query)
