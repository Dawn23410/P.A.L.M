"""run_code 执行前安全网：静态风险扫描 + 系统还原点 + 风险确认弹窗。"""
from __future__ import annotations

import os

from .schemas import AgentEvent
from .question_hub import get_question_hub
from palm._core.container import registry

# 评测/无人值守场景放行开关：P6 评测脚本经 HTTP API 驱动，无法应答 ask_user 弹窗，
# 而守卫的弹窗事件要等工具轮结束才随 SSE 下发（question_hub.wait 先于事件推送），
# 存在真实死锁（前端同样受影响）。评测设置本变量跳过弹窗直接放行。
_AUTOCONFIRM = os.environ.get("PALM_AUTOCONFIRM_RUN_CODE") == "1"


def _restore_module():
    """惰性取沙箱砖还原点模块；砖/能力缺失时返回 None（铁律：缺失降级）。"""
    brick = container.get("sandbox")
    restore_fn = brick.capabilities.get("restore_point") if brick else None
    return restore_fn() if restore_fn else None


# 系统级毁灭性操作的硬阻断清单：此类风险即使开启 _AUTOCONFIRM 也强制拦截，
# 防止评测/无人值守场景下误执行彻底破坏系统的代码。
_SYSTEM_DIRS = ("c:\\windows", "c:\\program files", "c:\\programdata",
                "/windows", "/sys", "/boot")
_DESTRUCTIVE_KEYS = ("rm -rf", "rmdir /s", "del /f", "os.remove", "shutil.rmtree",
                     "remove-item", "format ", "mkfs", "diskpart")


def _is_hard_blocked(code: str) -> bool:
    """检测系统级毁灭性代码（系统目录删除/全盘格式化），这类风险不可被 autoconfirm 放行。"""
    low = (code or "").lower()
    hits_system = any(d in low for d in _SYSTEM_DIRS)
    hits_destroy = any(k in low for k in _DESTRUCTIVE_KEYS)
    if hits_system and hits_destroy:
        return True
    if "rm -rf /" in low or "rm -rf ~" in low or "sudo rm -rf" in low:
        return True
    if "format " in low and ("c:" in low or "/dev/" in low):
        return True
    return False


def _scan_code_risks(code: str) -> list[str]:
    """静态扫描 run_code 代码的高危模式，返回可读风险列表（空表=无明显风险）。

    仅在编排层拦截，不依赖模型自觉——命中即弹窗征求用户同意。
    各检查拆为单职责函数，便于增删规则。
    """
    low = code.lower()
    risks: list[str] = []
    risks += _check_daemon_thread(low)
    risks += _check_destructive_delete(low)
    risks += _check_subproc_timeout(low)
    risks += _check_system_path_delete(low, code)
    risks += _check_detached_background(low, code)
    return risks


def _check_daemon_thread(low: str) -> list[str]:
    """daemon 后台线程且主线程未 join：子线程会被强杀、对话无法闭环。"""
    has_thread = ("thread(" in low or "threading" in low) and "daemon" in low
    if has_thread and ".join(" not in low:
        return ["代码使用了 daemon 后台线程且主线程未调用 join()：进程退出时子线程会被强杀，"
                "后台任务可能根本没执行完，且 run_code 会立即返回导致对话无法闭环"]
    return []


def _check_destructive_delete(low: str) -> list[str]:
    """破坏性删除操作：建议加 try 容错并二次确认路径。"""
    destructive = any(k in low for k in
                     ("os.remove", "os.rmdir", "shutil.rmtree", "shemptyrecyclebin",
                      "remove-item", "rm -rf", "rmdir /s", "del /f"))
    if destructive:
        return ["代码包含文件/回收站删除操作：建议加 try 容错并二次确认路径，避免误删。"
                "（已启用文件保险库：删除前会自动归档副本，可在「保险库」面板中找回）"]
    return []


def _check_subproc_timeout(low: str) -> list[str]:
    """子进程调用无超时：可能永久挂起，建议加 timeout 并同步回收。"""
    has_subproc = any(k in low for k in
                     ("subprocess", "popen(", "os.system", "start-process"))
    if has_subproc and "timeout" not in low:
        return ["代码调用子进程但未设置超时：可能永久挂起，建议加 timeout。"
                "若需等待子进程结果，请务必 .wait()/.communicate() 同步回收，否则对话无法闭环"]
    return []


def _check_system_path_delete(low: str, code: str) -> list[str]:
    """硬编码系统路径删除：风险较高，需用户确认路径无误。"""
    if ("c:\\users" in low and ("*" in code or "rm" in low)) or ("c:\\windows" in low and "rm" in low):
        return ["代码包含硬编码系统路径删除：风险较高，请确认路径无误"]
    return []


def _check_detached_background(low: str, code: str) -> list[str]:
    """疑似把任务 detach 到后台：run_code 立即返回、对话无法闭环。"""
    shell_bg = (" & " in code) or code.rstrip().endswith(" &") or ("start /b" in low) or ("nohup" in low)
    ps_bg = ("start-process" in low and "-wait" not in low)
    console_detach = ("create_new_console" in low or "detached_process" in low)
    popen_no_wait = ("popen(" in low) and ("communicate" not in low) and ("wait" not in low)
    if shell_bg or ps_bg or console_detach or popen_no_wait:
        return ["代码疑似把任务 detach 到后台（启动子进程/线程后不等待结果）：run_code 会立即返回、"
                "对话无法闭环，任务结果你拿不到也无法回复用户。除非已规划好持续跟进（如轮询或自动提醒），"
                "否则请改为同步等待：Popen 后调用 .wait()/.communicate()，或调大 run_code 的 timeout 同步跑完"]
    return []


def _collect_code_guard_risks(args: dict) -> list[str]:
    """汇总 run_code 的代码风险：静态扫描 + 提权请求。"""
    code = args.get("code", "") or ""
    risks = _scan_code_risks(code)
    if str(args.get("need_elevation", False)).lower() in ("true", "1", "yes"):
        risks.insert(0, "AI 请求以当前用户身份提权执行（将绕过沙箱隔离账户，获得当前用户对主用户资源"
                       "如主回收站、系统设置的操作权限）")
    return risks


def _detect_protection_disabled(agent) -> bool:
    """系统保护未开启时建还原点会静默失败，需先探测。"""
    try:
        restore = _restore_module()
        return restore is None or not restore.is_system_protection_enabled()
    except Exception:  # noqa: BLE001
        return False


async def _ask_enable_system_protection(agent, events: list) -> str:
    """弹窗询问是否开启系统保护。返回 blocked / enable / skip。

    ask_user 事件必须经即时队列在 wait 前推送（agent._ask_events），否则消费方收不到
    事件就无法应答、wait 永不返回。events 列表仅兼容旧调用方，实际不再依赖其下发。
    """
    spec = {
        "title": "系统保护未开启",
        "content": "创建「系统还原点」安全网需要开启 C 盘系统保护（仅占少量磁盘空间，"
                   "作为系统级回滚保险，不保护个人文件）。是否允许开启？",
        "qtype": "single",
        "options": ["开启并继续", "跳过(无回滚)", "取消"],
    }
    qid, spec = get_question_hub().create(agent._conversation_id, spec)
    ev = AgentEvent(type="ask_user", question=spec)
    events.append(ev)
    await _push_ask_event(agent, ev)
    answer = await get_question_hub().wait(qid)
    selected = answer.get("selected") if isinstance(answer, dict) else None
    if selected == "取消" or (isinstance(selected, str) and "取消" in selected):
        return "blocked"
    if selected and "开启" in str(selected):
        return "enable"
    return "skip"


def _try_enable_system_protection(agent, risks: list[str]) -> None:
    """尝试开启系统保护；失败则追加风险提示（本次无系统级回滚）。"""
    try:
        restore = _restore_module()
        if restore is None:
            risks.append("系统还原点模块不可用（沙箱砖未注册），本次执行无系统级回滚保护")
            return
        enabled = restore.enable_system_protection()
        if enabled.get("ok"):
            agent._protection_off = False
        else:
            risks.append("开启系统保护失败：%s（本次执行无系统级回滚保护）" % enabled.get("error"))
    except Exception as exc:  # noqa: BLE001
        risks.append("开启系统保护失败：%s（本次执行无系统级回滚保护）" % exc)


async def _run_system_protection_precheck(agent, events: list, risks: list[str]) -> str:
    """系统保护预检：按需弹窗开启。返回 blocked / ok。"""
    if not hasattr(agent, "_protection_off"):
        agent._protection_off = _detect_protection_disabled(agent)
    if not agent._protection_off or getattr(agent, "_protection_ask_done", False):
        return "ok"
    decision = await _ask_enable_system_protection(agent, events)
    agent._protection_ask_done = True
    if decision == "blocked":
        return "blocked"
    if decision == "enable":
        _try_enable_system_protection(agent, risks)
    return "ok"


def _create_restore_point(agent, risks: list[str]) -> None:
    """会话内仅自动建一次系统还原点，作为系统级回滚安全网。"""
    if getattr(agent, "_restore_point_created", False):
        return
    try:
        restore = _restore_module()
        snapshot = (restore.create_system_restore_point("代码执行前自动快照")
                    if restore else {"ok": False, "error": "沙箱砖未注册，还原点模块不可用"})
    except Exception as exc:  # noqa: BLE001
        snapshot = {"ok": False, "error": str(exc)}
    if snapshot.get("ok"):
        agent._restore_point_created = True
        if not snapshot.get("fresh"):
            risks.append("系统还原点已存在（24h 内合并，未生成新快照），本次执行前状态可能未被捕获")
    else:
        risks.append("系统还原点创建失败：%s（本次执行无系统级回滚保护）" % snapshot.get("error"))


async def _confirm_risk_dialog(agent, risks: list[str], events: list) -> str:
    """风险确认弹窗。返回 blocked / continue。

    ask_user 事件经即时队列在 wait 前推送，避免消费方无法应答导致的永久阻塞。
    """
    spec = {
        "title": "执行代码前的安全确认",
        "content": "检测到以下情况，请确认是否仍要执行：\n"
                   + "\n".join("• " + r for r in risks),
        "qtype": "single",
        "options": ["继续", "取消"],
    }
    qid, spec = get_question_hub().create(agent._conversation_id, spec)
    ev = AgentEvent(type="ask_user", question=spec)
    events.append(ev)
    await _push_ask_event(agent, ev)
    answer = await get_question_hub().wait(qid)
    selected = answer.get("selected") if isinstance(answer, dict) else None
    if selected == "取消" or (isinstance(selected, str) and "取消" in selected):
        return "blocked"
    return "continue"


async def _push_ask_event(agent, ev: AgentEvent) -> None:
    """把 ask_user 事件推送进 Agent 的即时事件队列（SSE 层并发消费）。

    Agent 未初始化队列（异常路径）时静默跳过，仅靠事件列表兜底，不阻塞安全流程。
    """
    queue = getattr(agent, "_ask_events", None)
    if queue is not None:
        await queue.put(ev)


async def _run_code_guard(agent, args: dict, events: list) -> str:
    """run_code 前置安全网：还原点 + 静态扫描，风险则弹窗征求用户同意。

    返回 "continue"（放行）或 "blocked"（用户拒绝）。事件直接 append 到 events。
    还原点会话内只自动建一次，作为系统级回滚安全网（不保护用户个人文件）。
    """
    risks = _collect_code_guard_risks(args)
    # M5：系统级毁灭性操作（系统目录删除/全盘格式化）不可被 autoconfirm 放行，
    # 必须强制拦截，避免评测/无人值守场景下彻底破坏系统。
    if _is_hard_blocked(args.get("code", "")):
        risks.append("检测到系统级毁灭性操作（系统目录删除/磁盘格式化），已强制拦截")
        return "blocked"
    if _AUTOCONFIRM:
        return "continue"
    if await _run_system_protection_precheck(agent, events, risks) == "blocked":
        return "blocked"
    _create_restore_point(agent, risks)
    if not risks:
        return "continue"
    return await _confirm_risk_dialog(agent, risks, events)


def _scan_shell_risks(command: str) -> list[str]:
    """扫描后台 shell 命令的高危模式（破坏性删除/格式化/系统目录/外网下载）。"""
    low = (command or "").lower()
    risks: list[str] = []
    destructive = any(k in low for k in
                     ("rm -rf", "rmdir /s", "del /f", "format ", "mkfs",
                      "diskpart", "os.remove", "shutil.rmtree", "remove-item"))
    if destructive:
        risks.append("后台命令包含破坏性删除/格式化操作：建议先确认路径，"
                     "删除前会自动归档到保险库（可在『保险库』面板找回）。")
    if ("c:\\windows" in low or "c:\\program files" in low) and destructive:
        risks.append("后台命令 targeting 系统目录：风险极高，请确认路径无误。")
    if any(k in low for k in ("curl", "wget", "invoke-webrequest", "invoke-restmethod")):
        risks.append("后台命令含网络下载：执行中可能访问外网，请确认来源可信。")
    return risks


async def guard_background_command(agent, command: str, events: list) -> str:
    """start_background_task 前置安全网：扫危险模式 + 建还原点 + 确认弹窗（H4 修复）。

    返回 "continue"（放行）或 "blocked"（用户拒绝/系统级风险）。系统级毁灭性操作
    不可被 autoconfirm 放行。
    """
    if _is_hard_blocked(command):
        events.append(AgentEvent(
            type="tool_result", tool_name="start_background_task",
            tool_output="[已拦截] 命令包含系统级毁灭性操作",
            adjudicated=True, adjudicated_reason="系统级硬阻断"))
        return "blocked"
    risks = _scan_shell_risks(command)
    if _AUTOCONFIRM:
        return "continue"
    if risks:
        # 危险命令执行前建系统还原点（best-effort，不保护个人文件）
        _create_restore_point(agent, risks)
        return await _confirm_risk_dialog(agent, risks, events)
    return "continue"