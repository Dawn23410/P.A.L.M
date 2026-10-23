"""扩展工具组（移植自 palm tools 子包）：生产工具 + 调度提醒 + 沙箱扩展。

- prod 工具（life_domestic_prod_tools.py）：成语 / 节日 / 汉字词典（在线，走网卡）/ 二维码（懒加载）。
- 调度提醒（scheduler_tools.py）：remind / schedule_task 适配进程内 Timer——
  触发后经 notify 回调（make_broker 注入 boss_core.receive）向心智魔方传达。
- 沙箱扩展（sandbox_tools.py）：create_restore_point / clear_restore_point /
  run_background_task（快照、清理、后台任务）。

权限：纯查询=compute；在线词典=web_read；二维码写文件=fs_write；
提醒=compute（仅登记本地通知）；沙箱扩展=shell（隔离目录内操作）。
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from pathlib import Path

from .cubes import ToolSpec
from .archived_tools import _resolve_allowed_path, sandbox

# 提醒推送回调（make_broker 接线时注入）：触发后向心智魔方传达提醒文本
_notify_ref = {"fn": None}


def _notify(text: str) -> None:
    fn = _notify_ref["fn"]
    if fn is not None:
        try:
            fn(text)
        except Exception:  # noqa: BLE001
            pass


# ── 生产工具（纯本地/在线查询）────────────────────────────
_CHENGYU_DB = {
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
_FESTIVALS = {
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


def _chengyu(args):
    query = (args.get("query") or "").strip()
    matches = [f"{k}：{v}" for k, v in _CHENGYU_DB.items()
               if query in k or query in v]
    if not matches:
        return f"未找到包含「{query}」的成语（内置 20 条常用成语）"
    return "\n".join(matches[:10])


def _festival(args):
    name = (args.get("name") or "").strip()
    for fn, desc in _FESTIVALS.items():
        if name and name in fn:
            return f"{fn}\n{desc}"
    return f"未找到「{name}」，已知节日：{'、'.join(_FESTIVALS)}"


def _chinese_dict(args):
    char = (args.get("char") or "").strip()
    if len(char) != 1 or not ("\u4e00" <= char <= "\u9fff"):
        return "请输入单个汉字"
    try:
        from .archived_tools import _safe_http_get
        r = _safe_http_get(f"https://baike.baidu.com/item/{char}", 8)
        r.raise_for_status()
        desc = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', r.text)
        py = re.search(r"拼音[：:]\s*([^\s,，<]+)", r.text)
        summary = f"汉字：{char}"
        if py:
            summary += f"\n拼音：{py.group(1)}"
        if desc:
            summary += f"\n{desc.group(1)[:200]}"
        else:
            summary += "\n（更多信息请查看百度百科）"
        return summary
    except Exception as exc:  # noqa: BLE001
        return f"汉字：{char}\nUnicode: U+{ord(char):04X}\n（在线查询失败：{type(exc).__name__}）"


def _generate_qrcode(args):
    content = (args.get("content") or "").strip()
    save_path = (args.get("save_path") or "").strip()
    if not content or not save_path:
        return "需要 content 与 save_path 参数"
    try:
        import qrcode
    except ImportError:
        return "需要安装 qrcode 库：pip install qrcode[pil]"
    try:
        safe = _resolve_allowed_path(save_path)
    except PermissionError as exc:
        return f"拒绝：{exc}"
    img = qrcode.make(content)
    img.save(safe)
    return f"二维码已保存到 {safe}（内容：{content[:50]}）"


def _prod_specs() -> list[ToolSpec]:
    return [
        ToolSpec("chengyu", "查询成语含义（内置 20 条，支持模糊搜索）",
                 ["compute"], False, _chengyu,
                 {"type": "object", "properties": {"query": {"type": "string"}},
                  "required": ["query"]}),
        ToolSpec("festival", "查询中国传统节日信息（内置 10 个主要节日）",
                 ["compute"], False, _festival,
                 {"type": "object", "properties": {"name": {"type": "string"}},
                  "required": ["name"]}),
        ToolSpec("chinese_dict", "汉字基本信息查询（在线百度百科，含拼音与简介）",
                 ["web_read"], False, _chinese_dict,
                 {"type": "object", "properties": {"char": {"type": "string"}},
                  "required": ["char"]}),
        ToolSpec("generate_qrcode", "生成二维码图片并保存到指定路径",
                 ["fs_write"], False, _generate_qrcode,
                 {"type": "object", "properties": {
                     "content": {"type": "string"}, "save_path": {"type": "string"}},
                  "required": ["content", "save_path"]}),
    ]


# ── 调度提醒（进程内 Timer，触发经心智魔方传达）────────────
def _parse_delay(when: str) -> float | None:
    """解析触发延迟秒数：ISO 时间差 / 'N 分钟' / 'N 秒'；无法解析返回 None。"""
    w = (when or "").strip().lower()
    m = re.match(r"^(\d+)\s*(秒|s|分钟|min|小时|h)?$", w)
    if m:
        unit = m.group(2) or "秒"
        mult = {"秒": 1, "s": 1, "分钟": 60, "min": 60, "小时": 3600, "h": 3600}[unit]
        return float(m.group(1)) * mult
    if "t" in w and "-" in w and ":" in w:  # ISO 时间
        try:
            from datetime import datetime
            target = datetime.fromisoformat(w.replace("Z", ""))
            return max(0.0, (target - datetime.now()).total_seconds())
        except ValueError:
            return None
    return None


def _schedule_job(text: str, when: str) -> str:
    delay = _parse_delay(when)
    if delay is None:
        return ("无法解析提醒时间，请使用：'N 秒/分钟/小时' 或 ISO 时间"
                "（如 2026-08-05T09:00）。")
    if delay > 0:
        threading.Timer(delay, _notify, args=(f"[提醒] {text}",)).start()
    return f"已设置提醒：{delay:.0f} 秒后触发「{text[:40]}」"


def _remind(args):
    return _schedule_job(args.get("text", ""), args.get("when", ""))


def _schedule_task(args):
    sched_type = (args.get("schedule_type") or "once").lower()
    value = (args.get("schedule_value") or "").strip()
    if sched_type in ("once", "interval"):
        return _schedule_job(args.get("brief") or args.get("title", ""), value)
    if sched_type == "cron":
        from .cron import Cron, CRON_ALIASES
        expr = CRON_ALIASES.get(value.lower(), value)
        cron = Cron(expr)
        if cron.invalid:
            return ("无效 cron 表达式：需 5 字段（分 时 日 月 周），"
                    "或 daily/weekly/monthly 别名。")
        nxt = cron.next_time()
        if nxt is None:
            return "cron 在 24 小时内无触发点，请检查表达式。"
        from datetime import datetime
        delay = max(1.0, (nxt - datetime.now()).total_seconds())
        return _schedule_job(args.get("brief") or args.get("title", ""), f"{delay:.0f} 秒")
    return ("本进程仅支持 once/interval/cron 触发；rrule 周期任务请交给宿主调度"
            "（Worker 是短生命周期执行体，不适合常驻周期任务）。")


def _scheduler_specs() -> list[ToolSpec]:
    return [
        ToolSpec("remind", "设置提醒：在指定时间后向心智魔方推送一条提醒（进程内定时）",
                 ["compute"], False, _remind,
                 {"type": "object", "properties": {
                     "text": {"type": "string", "description": "提醒内容"},
                     "when": {"type": "string",
                              "description": "'N 秒/分钟/小时' 或 ISO 时间"}},
                  "required": ["text", "when"]}),
        ToolSpec("schedule_task", "创建周期性主动推送任务（本进程支持 once/interval）",
                 ["compute"], False, _schedule_task,
                 {"type": "object", "properties": {
                     "title": {"type": "string"}, "brief": {"type": "string"},
                     "schedule_type": {"type": "string",
                                       "description": "once|interval|cron|rrule"},
                     "schedule_value": {"type": "string"}},
                  "required": ["title", "brief", "schedule_type", "schedule_value"]}),
    ]


# ── 沙箱扩展（快照 / 后台任务）────────────────────────────
def _restore_root() -> str:
    cube = sandbox()
    if cube is None:
        raise RuntimeError("沙箱不可用")
    root = os.path.join(cube.directory, "_restore_points")
    Path(root).mkdir(parents=True, exist_ok=True)
    return root


def _create_restore_point(args):
    name = (args.get("name") or time.strftime("%Y%m%d_%H%M%S"))
    cube = sandbox()
    if cube is None:
        return "（沙箱不可用，拒绝创建还原点）"
    root = _restore_root()
    dst = os.path.join(root, name)
    if os.path.exists(dst):
        return f"还原点已存在：{name}"
    shutil.copytree(cube.directory, dst,
                    ignore=shutil.ignore_patterns("_restore_points", "_vault", "_trash"))
    return f"已创建还原点：{name}（沙箱快照）"


def _clear_restore_point(args):
    root = _restore_root()
    name = (args.get("name") or "").strip()
    if name:
        target = os.path.join(root, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
            return f"已清理还原点：{name}"
        return f"还原点不存在：{name}"
    shutil.rmtree(root, ignore_errors=True)
    Path(root).mkdir(parents=True, exist_ok=True)
    return "已清理全部还原点"


def _run_background_task(args):
    cube = sandbox()
    if cube is None:
        return "（沙箱不可用，拒绝后台任务）"
    cmd = (args.get("cmd") or "").strip()
    if not cmd:
        return "（无命令）"
    ref = {"started": time.strftime("%H:%M:%S")}

    def _worker():
        try:
            out = cube.run(cmd, timeout=300)
            _notify(f"[后台任务完成] {cmd[:40]}\n结果：{out[:200]}")
        except Exception as exc:  # noqa: BLE001
            _notify(f"[后台任务失败] {cmd[:40]}：{type(exc).__name__}")

    threading.Thread(target=_worker, daemon=True, name="exo-bg-task").start()
    return f"后台任务已启动（{ref['started']}）：{cmd[:60]}，完成后经心智魔方传达结果"


def _sandbox_ext_specs() -> list[ToolSpec]:
    return [
        ToolSpec("create_restore_point", "为沙箱目录创建快照还原点",
                 ["shell"], False, _create_restore_point,
                 {"type": "object", "properties": {"name": {"type": "string"}}}),
        ToolSpec("clear_restore_point", "清理沙箱还原点（可指定名称或全部）",
                 ["shell"], False, _clear_restore_point,
                 {"type": "object", "properties": {"name": {"type": "string"}}}),
        ToolSpec("run_background_task", "在沙箱后台执行长任务，完成后经心智魔方传达结果",
                 ["shell"], False, _run_background_task,
                 {"type": "object", "properties": {"cmd": {"type": "string"}},
                  "required": ["cmd"]}),
    ]


def register_extended_tools(tool_cube, *, notify=None) -> None:
    """注册扩展工具组（prod 4 + scheduler 2 + 沙箱 3）；notify 为提醒推送回调。"""
    if notify is not None:
        _notify_ref["fn"] = notify
    for spec in _prod_specs() + _scheduler_specs() + _sandbox_ext_specs():
        tool_cube.register(spec)
