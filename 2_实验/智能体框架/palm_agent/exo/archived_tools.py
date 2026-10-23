"""归档工具组（移植自 palm/services/agent/tools）：文件 10 + 网络 2 + run_code + ask_user。

- 文件工具逻辑沿用归档实现（去 palm Tool 基类，同步 fn(args)->str），
  路径白名单：仅允许操作用户主目录内文件（_resolve_allowed_path）。
- 网络工具沿用归档 SSRF 防护（目标主机校验）+ 手动有限跳数跟随。
- run_code：代码写入沙箱目录临时文件后经沙箱魔方执行（fail-closed）。
- ask_user：经心智魔方中转——Worker 提问 → Boss 传达 → 阻塞取用户回复（ask_bridge）。

权限标签对齐 exo 权限闸门：读=fs_read / 写=fs_write / 网络=web_read / 代码=compute / 询问=ask。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from .cubes import ToolSpec

_USER_HOME = os.path.normcase(os.path.abspath(os.path.expanduser("~")))


def _resolve_allowed_path(raw_path: str) -> str:
    """校验并归一化路径：必须落在用户主目录内（解析符号链接后），否则拒绝。"""
    resolved = os.path.normcase(
        os.path.realpath(os.path.expanduser(str(raw_path))))
    if resolved == _USER_HOME or resolved.startswith(_USER_HOME + os.sep):
        return resolved
    raise PermissionError(
        "路径越权：文件工具仅允许操作用户主目录内的文件（%s 之外被拒绝）。" % _USER_HOME)


# ── 文件工具（10 个可执行 + delete 安全版）──────────────────
def _read_file(args):
    safe = _resolve_allowed_path(args["path"])
    with open(safe, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(args):
    safe = _resolve_allowed_path(args["path"])
    Path(safe).parent.mkdir(parents=True, exist_ok=True)
    with open(safe, "w", encoding="utf-8") as f:
        f.write(args["content"])
    return f"已写入 {len(args['content'])} 字符到 {safe}"


def _append_file(args):
    safe = _resolve_allowed_path(args["path"])
    with open(safe, "a", encoding="utf-8") as f:
        f.write(args["content"])
    return f"已追加 {len(args['content'])} 字符"


def _copy_file(args):
    shutil.copy2(_resolve_allowed_path(args["src"]), _resolve_allowed_path(args["dst"]))
    return f"已复制 {args['src']} → {args['dst']}"


def _move_file(args):
    shutil.move(_resolve_allowed_path(args["src"]), _resolve_allowed_path(args["dst"]))
    return f"已移动 {args['src']} → {args['dst']}"


_VAULT_DIR = os.environ.get("MENTALCORE_EXO_VAULT_DIR", "")


def _delete_file(args):
    """安全删除（对齐归档保险库 H2）：先归档副本到保险库，再移入回收目录，杜绝永久硬删。"""
    safe = _resolve_allowed_path(args["path"])
    if not os.path.exists(safe):
        return f"文件不存在：{safe}"
    cube = sandbox()
    if cube is None:
        return "拒绝永久删除（安全策略）：请经心智魔方确认后在宿主侧处理。"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    vault_root = _VAULT_DIR or os.path.join(cube.directory, "_vault")
    vault_dir = os.path.join(vault_root, stamp)
    Path(vault_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy2(safe, os.path.join(vault_dir, os.path.basename(safe)))
    trash = os.path.join(cube.directory, "_trash", stamp)
    Path(trash).mkdir(parents=True, exist_ok=True)
    dst = os.path.join(trash, os.path.basename(safe))
    shutil.move(safe, dst)
    return (f"已删除并归档副本到保险库：{vault_dir}（非永久删除，可从保险库找回）")


def _list_directory(args):
    safe = _resolve_allowed_path(args["path"])
    items = os.listdir(safe)
    files, dirs = [], []
    for item in items:
        (dirs if os.path.isdir(os.path.join(safe, item)) else files).append(item)
    text = f"{len(dirs)} 目录 | {len(files)} 文件"
    if dirs:
        text += "\n目录:\n" + "\n".join(f"  {d}" for d in sorted(dirs))
    if files:
        text += "\n文件:\n" + "\n".join(f"  {f}" for f in sorted(files))
    return text


def _get_file_info(args):
    safe = _resolve_allowed_path(args["path"])
    stat = os.stat(safe)
    size = stat.st_size
    size_str = (f"{size}B" if size < 1024 else
                f"{size/1024:.1f}KB" if size < 1048576 else
                f"{size/1048576:.1f}MB" if size < 1073741824 else f"{size/1073741824:.1f}GB")
    return json.dumps({
        "path": safe, "size": size_str, "bytes": size,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(stat.st_mtime)),
    }, ensure_ascii=False, indent=2)


def _search_files(args):
    safe = _resolve_allowed_path(args["root"])
    keyword = (args.get("keyword") or "").lower()
    max_results = int(args.get("max_results") or 20)
    matches = []
    for dirpath, _, filenames in os.walk(safe):
        for f in filenames:
            if keyword in f.lower():
                matches.append(os.path.join(dirpath, f))
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break
    return (f"找到 {len(matches)} 个文件:\n" + "\n".join(matches)
            if matches else "未找到匹配文件")


def _file_hash(args):
    safe = _resolve_allowed_path(args["path"])
    algo = (args.get("algorithm") or "sha256").lower()
    h = hashlib.md5() if algo == "md5" else hashlib.sha256()
    with open(safe, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"{algo.upper()}: {h.hexdigest()}"


def _create_directory(args):
    safe = _resolve_allowed_path(args["path"])
    Path(safe).mkdir(parents=True, exist_ok=True)
    return f"已创建目录 {safe}"


# ── 网络工具（SSRF 防护 + 手动跳数跟随）────────────────────
def _is_safe_host(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    candidates: set[str] = set()
    if host.replace(".", "").isdigit() or ":" in host:
        candidates.add(host)
    else:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        candidates.update(info[4][0] for info in infos)
    for ip_str in candidates:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    return True


def _safe_http_get(url: str, timeout: int):
    """安全 GET（经网卡门面）：关闭自动重定向，手动有限跳数跟随，每跳校验主机。"""
    if not _is_safe_host(url):
        raise RuntimeError("目标地址为内网/保留地址，已阻止（SSRF 防护）")
    resp = _fetch(url, timeout)
    hops = 0
    while resp.status_code in (301, 302, 303, 307, 308) and hops < 5:
        location = resp.headers.get("location")
        if not location or not _is_safe_host(location):
            raise RuntimeError("重定向目标为内网/保留地址，已阻止（SSRF 防护）")
        resp = _fetch(location, timeout)
        hops += 1
    return resp


def _fetch(url: str, timeout: int):
    """同步桥接 palm 网卡 arequest（网络 loop 线程内执行）。"""
    from palm._core.net import arequest
    from .model import _run_sync

    async def _run():
        return await arequest("GET", url, timeout=timeout, follow_redirects=False)
    return _run_sync(_run())


def _html_to_text(html: str, limit: int = 6000) -> str:
    import re
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _extract_search_results(html: str, max_results: int = 6) -> list:
    import re
    results = []
    blocks = re.findall(r'<li class="b_algo[^"]*".*?</li>', html,
                        flags=re.DOTALL | re.IGNORECASE)
    for block in blocks:
        href = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"', block,
                         flags=re.IGNORECASE)
        if not href or not re.match(r'https?://', href.group(1), re.IGNORECASE):
            continue
        title = re.search(r'<h2[^>]*>\s*<a[^>]*>(.*?)</a>', block,
                          flags=re.DOTALL | re.IGNORECASE)
        snippet = re.search(r'<p[^>]*>(.*?)</p>', block,
                            flags=re.DOTALL | re.IGNORECASE)
        results.append({
            "title": re.sub(r'<[^>]+>', '', title.group(1)).strip() if title else "",
            "url": href.group(1),
            "snippet": re.sub(r'<[^>]+>', '', snippet.group(1)).strip() if snippet else "",
        })
        if len(results) >= max_results:
            break
    return results


def _web_search(args):
    from urllib.parse import quote
    try:
        r = _safe_http_get(
            f"https://www.bing.com/search?q={quote(args['query'])}"
            "&setlang=zh-CN&cc=CN", 15)
        r.raise_for_status()
        results = _extract_search_results(r.text)
        if not results:
            return f"未找到与「{args['query']}」相关的搜索结果。"
        lines = [f"搜索「{args['query']}」得到 {len(results)} 条结果："]
        for i, item in enumerate(results, 1):
            lines.append(f"{i}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"搜索失败: {exc}"


def _web_fetch(args):
    try:
        r = _safe_http_get(args["url"], 30)
        r.raise_for_status()
        return _html_to_text(r.text) if "<" in r.text[:200] else r.text[:6000]
    except Exception as exc:  # noqa: BLE001
        return f"抓取失败: {exc}"


# ── run_code（沙箱执行）─────────────────────────────────────
_sandbox_ref = {"cube": None}


def _bind_sandbox(sandbox_cube):
    _sandbox_ref["cube"] = sandbox_cube


def sandbox():
    return _sandbox_ref["cube"]


def _run_code(args):
    cube = sandbox()
    if cube is None:
        return "（沙箱不可用，拒绝执行代码）"
    code = (args.get("code") or "").strip()
    lang = (args.get("language") or "python").lower()
    if not code:
        return "（无代码可执行）"
    from .cubes.code_guard import guard_code
    blocked = guard_code(code)
    if blocked:
        return blocked
    ext = {"python": "py", "node": "js", "bash": "sh"}.get(lang, "py")
    runner = {"python": "python", "node": "node", "bash": "bash"}.get(lang, "python")
    fname = f"_exo_code_{int(time.time())}.{ext}"
    path = os.path.join(cube.directory, fname)
    Path(path).write_text(code, encoding="utf-8")
    return cube.run(f"{runner} {fname}")


# ── 工具注册表 ──────────────────────────────────────────────
def _file_specs() -> list[ToolSpec]:
    p = "path"
    return [
        ToolSpec("read_file", "读取本地文件内容（纯文本），路径为绝对路径",
                 ["fs_read"], False, _read_file,
                 {"type": "object", "properties": {p: {"type": "string"}}, "required": [p]}),
        ToolSpec("write_file", "将文本内容写入本地文件。路径为绝对路径。",
                 ["fs_write"], False, _write_file,
                 {"type": "object", "properties": {p: {"type": "string"},
                                                   "content": {"type": "string"}},
                  "required": [p, "content"]}),
        ToolSpec("append_file", "追加内容到文件末尾",
                 ["fs_write"], False, _append_file,
                 {"type": "object", "properties": {p: {"type": "string"},
                                                   "content": {"type": "string"}},
                  "required": [p, "content"]}),
        ToolSpec("copy_file", "复制文件到目标路径",
                 ["fs_write"], False, _copy_file,
                 {"type": "object", "properties": {"src": {"type": "string"},
                                                   "dst": {"type": "string"}},
                  "required": ["src", "dst"]}),
        ToolSpec("move_file", "移动/重命名文件到目标路径",
                 ["fs_write"], False, _move_file,
                 {"type": "object", "properties": {"src": {"type": "string"},
                                                   "dst": {"type": "string"}},
                  "required": ["src", "dst"]}),
        ToolSpec("delete_file", "删除指定文件（安全策略：移入回收目录，非永久删除）",
                 ["fs_write"], False, _delete_file,
                 {"type": "object", "properties": {p: {"type": "string"}}, "required": [p]}),
        ToolSpec("list_directory", "列出目录下所有文件和子目录",
                 ["fs_read"], False, _list_directory,
                 {"type": "object", "properties": {p: {"type": "string"}}, "required": [p]}),
        ToolSpec("get_file_info", "获取文件大小、修改时间等元信息",
                 ["fs_read"], False, _get_file_info,
                 {"type": "object", "properties": {p: {"type": "string"}}, "required": [p]}),
        ToolSpec("search_files", "按文件名关键词搜索文件",
                 ["fs_read"], False, _search_files,
                 {"type": "object", "properties": {
                     "root": {"type": "string"}, "keyword": {"type": "string"},
                     "max_results": {"type": "integer", "default": 20}},
                  "required": ["root", "keyword"]}),
        ToolSpec("file_hash", "计算文件的 MD5/SHA256 哈希值",
                 ["fs_read"], False, _file_hash,
                 {"type": "object", "properties": {
                     p: {"type": "string"},
                     "algorithm": {"type": "string", "enum": ["md5", "sha256"],
                                   "default": "sha256"}},
                  "required": [p]}),
        ToolSpec("create_directory", "创建目录（含父目录）",
                 ["fs_write"], False, _create_directory,
                 {"type": "object", "properties": {p: {"type": "string"}}, "required": [p]}),
    ]


def _web_specs() -> list[ToolSpec]:
    return [
        ToolSpec("web_search",
                 "搜索互联网信息，返回前若干条结果的标题、链接与摘要，"
                 "便于进一步用 web_fetch 抓取详情。",
                 ["web_read"], False, _web_search,
                 {"type": "object", "properties": {
                     "query": {"type": "string", "description": "搜索关键词"}},
                  "required": ["query"]}),
        ToolSpec("web_fetch", "获取并提取网页正文文本（已去除脚本/样式等噪声）",
                 ["web_read"], False, _web_fetch,
                 {"type": "object", "properties": {
                     "url": {"type": "string", "description": "目标网页地址"}},
                  "required": ["url"]}),
    ]


def _run_code_spec() -> ToolSpec:
    return ToolSpec("run_code", "在沙箱内运行代码（python/node/bash）",
                    ["compute"], False, _run_code,
                    {"type": "object", "properties": {
                        "language": {"type": "string",
                                     "enum": ["python", "node", "bash"],
                                     "default": "python"},
                        "code": {"type": "string", "description": "要运行的代码"}},
                     "required": ["code"]})


# ask 桥运行时引用：装配时注册工具（桥可能尚未就绪），make_broker 接线时更新。
# 不用闭包固化——否则接线发生在注册之后时，工具拿到的永远是 None。
_ask_ref = {"bridge": None}


def _ask_spec() -> ToolSpec:
    def _ask(args):
        bridge = _ask_ref["bridge"]
        if bridge is None:
            return "（后台无交互通道：Worker 未接心智魔方，无法询问用户）"
        return bridge(str(args.get("question", "")))
    return ToolSpec("ask_user", "向用户提问（经心智魔方传达，等待用户回复）",
                    ["ask"], False, _ask,
                    {"type": "object", "properties": {
                        "question": {"type": "string", "description": "要问用户的问题"}},
                     "required": ["question"]})


# ── GUI 自动化（palm adapters/gui 砖：execute_gui_intent 闭环）────────
def _gui_automate(args):
    """桌面 GUI 自动化：经推理中枢→执行器闭环执行一个界面意图（懒加载，fail-operational）。"""
    from .model import _run_sync

    async def _run():
        from palm.adapters.gui.automation_orchestrator import execute_gui_intent
        return await execute_gui_intent(
            software_id=str(args.get("software_id") or "desktop"),
            intent=str(args.get("intent") or ""),
            target_hwnd=args.get("target_hwnd"))
    try:
        result = _run_sync(_run())
    except Exception as exc:  # noqa: BLE001
        return f"GUI 自动化失败（无桌面环境或砖不可用）：{str(exc)[:200]}"
    if isinstance(result, dict):
        mark = "完成" if result.get("exec_success") else "未完成"
        return (f"GUI 意图：{mark}（source={result.get('source')}, "
                f"trust={result.get('trust')}）\n{str(result.get('note') or '')[:500]}")
    return str(result)[:500]


def _gui_spec() -> ToolSpec:
    return ToolSpec("automate",
                    "桌面 GUI 自动化：对指定软件执行界面操作意图（点击/输入/切换设置/窗口操作等），"
                    "用自然语言描述要做的事",
                    ["gui"], False, _gui_automate,
                    {"type": "object", "properties": {
                        "software_id": {"type": "string",
                                        "description": "目标软件标识（desktop 或软件名/浏览器 id）"},
                        "intent": {"type": "string",
                                   "description": "要执行的界面操作意图，用自然语言描述"}},
                     "required": ["intent"]})


def register_archived_tools(tool_cube, *, sandbox_cube=None, ask_bridge=None) -> None:
    """把归档工具组注册进工具魔方（文件 10 + 网络 2 + run_code + ask_user + GUI automate）。"""
    _bind_sandbox(sandbox_cube)
    if ask_bridge is not None:
        _ask_ref["bridge"] = ask_bridge
    for spec in _file_specs() + _web_specs():
        tool_cube.register(spec)
    tool_cube.register(_run_code_spec())
    tool_cube.register(_ask_spec())
    tool_cube.register(_gui_spec())
