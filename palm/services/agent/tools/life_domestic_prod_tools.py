"""国内特色工具 + 需专用库的产能工具（精简保留：数据型/依赖库，无法被 run_code 干净替代）。"""
from __future__ import annotations

import json, logging, os, time
from ..tool_base import Tool

from palm._core.net import arequest

_LOGGER = logging.getLogger(__name__)


# ── 国内特色工具 ────────────────────────────────────────

class ChengyuTool(Tool):
    """成语查询（内置 20 条常用成语）。"""
    _chengyu_db = {
        "一心一意": "形容专心致志，没有杂念。", "三心二意": "形容犹豫不决或意志不坚定。",
        "五光十色": "形容色彩鲜艳、繁多。", "十全十美": "各方面都非常完美，毫无缺陷。",
        "百发百中": "形容射击、打击非常准确。", "千军万马": "形容雄壮的队伍或浩大的声势。",
        "画龙点睛": "比喻在关键处用几句话点明实质。", "对牛弹琴": "比喻说话不看对象。",
        "守株待兔": "比喻不主动努力，存侥幸心理。", "亡羊补牢": "出了问题后想办法补救。",
        "井底之蛙": "比喻见识狭窄的人。", "叶公好龙": "比喻口头爱好，实际并非如此。",
        "掩耳盗铃": "比喻自己欺骗自己。", "刻舟求剑": "办事刻板，不知变通。",
        "狐假虎威": "比喻仗势欺人。", "画蛇添足": "做了多余的事，反而不好。",
        "自相矛盾": "言行互相抵触。", "坐井观天": "比喻眼界狭窄，见识有限。",
        "愚公移山": "比喻坚持不懈。", "精卫填海": "比喻意志坚决。",
    }
    @property
    def name(self) -> str: return "chengyu"
    @property
    def description(self) -> str: return "查询成语含义（支持模糊搜索）"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string", "description": "成语或关键词"}}, "required": ["query"]}
    async def execute(self, query: str) -> str:
        matches = []
        for idiom, meaning in self._chengyu_db.items():
            if query in idiom or query in meaning:
                matches.append(f"📖 {idiom}：{meaning}")
        if not matches:
            return f"未找到包含「{query}」的成语"
        return "\n".join(matches[:10])


class FestivalTool(Tool):
    """中国传统节日查询（内置 10 个主要节日）。"""
    _festivals = {
        "春节": "正月初一，中国最重要的传统节日，家人团聚、吃年夜饭、发红包。",
        "元宵节": "正月十五，赏花灯、吃汤圆、猜灯谜。",
        "清明节": "4月5日前后，扫墓祭祖、踏青郊游。",
        "端午节": "五月初五，吃粽子、赛龙舟、挂艾草。",
        "七夕节": "七月初七，中国情人节，牛郎织女相会。",
        "中秋节": "八月十五，团圆赏月、吃月饼。",
        "重阳节": "九月初九，登高望远、敬老爱老。",
        "腊八节": "十二月初八，喝腊八粥、祈福。",
        "小年": "十二月二十三/二十四，祭灶神、扫尘。",
        "除夕": "十二月最后一天，守岁、吃年夜饭、贴春联。",
    }
    @property
    def name(self) -> str: return "festival"
    @property
    def description(self) -> str: return "查询中国传统节日信息"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"name": {"type": "string", "description": "节日名称"}}, "required": ["name"]}
    async def execute(self, name: str) -> str:
        for fn, desc in self._festivals.items():
            if name in fn:
                return f"🎊 {fn}\n{desc}"
        return f"未找到「{name}」，已知节日：{'、'.join(self._festivals.keys())}"


class ChineseDictTool(Tool):
    """汉字基本信息查询 —— 在线百度百科。"""
    @property
    def name(self) -> str: return "chinese_dict"
    @property
    def description(self) -> str: return "汉字基本信息查询（笔画/部首/拼音占位）"
    @property
    def tool_permission(self) -> str: return "network.http_outbound"
    @property
    def tool_event_type(self) -> str: return "network.request"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"char": {"type": "string", "description": "单个汉字"}}, "required": ["char"]}
    async def execute(self, char: str) -> str:
        if len(char) != 1 or not ('\u4e00' <= char <= '\u9fff'):
            return "请输入单个汉字"
        try:
            # 经网卡门面转发（外网 GET，默认拒绝未授权主机）。
            r = await arequest("GET", f"https://baike.baidu.com/item/{char}",
                               headers={"User-Agent": "Mozilla/5.0"},
                               timeout=8, follow_redirects=True)
            import re
            desc = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', r.text)
            py = re.search(r'拼音[：:]\s*([^\s,，<]+)', r.text)
            summary = f"🔤 汉字：{char}"
            if py: summary += f"\n拼音：{py.group(1)}"
            if desc: summary += f"\n{desc.group(1)[:200]}"
            else: summary += "\n（更多信息请查看百度百科）"
            return summary
        except Exception as exc:
            _LOGGER.warning("汉字在线查询失败（%s）: %s", char, exc)
            return f"🔤 汉字：{char}\nUnicode: U+{ord(char):04X}\n（在线查询失败）"


CN_TOOLS = [ChengyuTool, FestivalTool, ChineseDictTool]


# ── 需专用库的产能工具 ─────────────────────────────────

class QRCodeTool(Tool):
    @property
    def name(self) -> str: return "generate_qrcode"
    @property
    def description(self) -> str: return "生成二维码（需要安装 qrcode 库）"
    @property
    def tool_permission(self) -> str: return "file.write"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"content": {"type": "string"}, "save_path": {"type": "string"}}, "required": ["content", "save_path"]}
    async def execute(self, content: str, save_path: str) -> str:
        try:
            import qrcode
            img = qrcode.make(content)
            img.save(save_path)
            return f"✅ 二维码已保存到 {save_path}（内容: {content[:50]}）"
        except ImportError:
            return "需要安装 qrcode 库: pip install qrcode[pil]"


PROD_TOOLS = [ChengyuTool, FestivalTool, ChineseDictTool, QRCodeTool]
