"""文件操作类工具（11 个）。

安全要求（配合安全审计 H2/H3/M9）：
- 删除必须走 safe_delete（先归档保险库再移回收站），杜绝永久硬删。
- 所有路径限定在用户主目录内，禁止越权读写系统/他人文件。
- 只读工具补 event_type，使其进入裁决引擎（无规则则默认放行，不增摩擦）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from palm_sdk.core.config import settings
from ..tool_base import Tool

# 用户主目录（路径白名单根）：文件工具只允许操作用户主目录内的文件，
# 杜绝 AI 越权读取/修改系统目录、其他用户文件或 SSH 密钥等敏感位置。
_USER_HOME = os.path.normcase(os.path.abspath(os.path.expanduser("~")))


def _send_to_recycle_bin(path: str) -> None:
    """经存储砖冗余层取删除守卫（先归档保险库再移回收站）。

    砖缺失时抛 RuntimeError 而非裸删降级：删除兜底是本工具的安全前提，
    守卫不可用时宁可让工具失败，也不允许绕过硬删。
    """
    from palm_sdk.bricks.base import registry
    brick = registry.get("storage")
    recycle_fn = brick.capabilities.get("recycle_bin") if brick else None
    if recycle_fn is None:
        raise RuntimeError("存储砖未注册，文件删除守卫不可用")
    return recycle_fn()(path)


def _resolve_allowed_path(raw_path: str) -> str:
    """校验并归一化路径：必须落在用户主目录内（解析符号链接后），否则拒绝。

    返回真实绝对路径；越权时抛 PermissionError（由调用方转成工具错误文本）。
    """
    resolved = os.path.normcase(
        os.path.realpath(os.path.expanduser(str(raw_path))))
    if resolved == _USER_HOME or resolved.startswith(_USER_HOME + os.sep):
        return resolved
    raise PermissionError(
        "路径越权：文件工具仅允许操作用户主目录内的文件（%s 之外被拒绝）。" % _USER_HOME)


class ReadFileTool(Tool):
    @property
    def name(self) -> str: return "read_file"
    @property
    def description(self) -> str: return "读取本地文件内容（纯文本），路径为绝对路径"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.read"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string", "description": "文件绝对路径"}}, "required": ["path"]}
    async def execute(self, path: str) -> str:
        safe_path = _resolve_allowed_path(path)
        with open(safe_path, "r", encoding="utf-8") as f:
            return f.read()


class WriteFileTool(Tool):
    @property
    def name(self) -> str: return "write_file"
    @property
    def description(self) -> str: return "将文本内容写入本地文件。路径为绝对路径。"
    @property
    def event_type(self) -> str: return "file.write"
    @property
    def tool_permission(self) -> str: return "file.write"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    async def execute(self, path: str, content: str) -> str:
        safe_path = _resolve_allowed_path(path)
        Path(safe_path).parent.mkdir(parents=True, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {len(content)} 字符到 {safe_path}"


class AppendFileTool(Tool):
    @property
    def name(self) -> str: return "append_file"
    @property
    def description(self) -> str: return "追加内容到文件末尾"
    @property
    def event_type(self) -> str: return "file.write"
    @property
    def tool_permission(self) -> str: return "file.write"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    async def execute(self, path: str, content: str) -> str:
        safe_path = _resolve_allowed_path(path)
        with open(safe_path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"已追加 {len(content)} 字符"


class CopyFileTool(Tool):
    @property
    def name(self) -> str: return "copy_file"
    @property
    def description(self) -> str: return "复制文件到目标路径"
    @property
    def event_type(self) -> str: return "file.write"
    @property
    def tool_permission(self) -> str: return "file.write"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]}
    async def execute(self, src: str, dst: str) -> str:
        safe_src = _resolve_allowed_path(src)
        safe_dst = _resolve_allowed_path(dst)
        shutil.copy2(safe_src, safe_dst)
        return f"已复制 {safe_src} → {safe_dst}"


class MoveFileTool(Tool):
    @property
    def name(self) -> str: return "move_file"
    @property
    def description(self) -> str: return "移动/重命名文件到目标路径"
    @property
    def event_type(self) -> str: return "file.write"
    @property
    def tool_permission(self) -> str: return "file.write"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]}
    async def execute(self, src: str, dst: str) -> str:
        safe_src = _resolve_allowed_path(src)
        safe_dst = _resolve_allowed_path(dst)
        shutil.move(safe_src, safe_dst)
        return f"已移动 {safe_src} → {safe_dst}"


class DeleteFileTool(Tool):
    @property
    def name(self) -> str: return "delete_file"
    @property
    def description(self) -> str: return "删除指定文件（删除前自动归档到保险库，可从『保险库』面板找回）"
    @property
    def event_type(self) -> str: return "file.delete"
    @property
    def tool_permission(self) -> str: return "file.delete"
    # verification_gate 样例：删除必须显式确认，且要求经搜索/溯源核验附带 verification_id，
    # 否则执行前直接硬拦截（不依赖 AI 自觉，补强 H2 的回收站兜底）。
    @property
    def requires_grounding(self) -> bool: return True
    @property
    def requires_confirmation(self) -> bool: return True
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {
            "path": {"type": "string"},
            "verification_id": {"type": "string", "description": "溯源核验令牌（来自前置搜索/确认）"},
            "confirmed": {"type": "boolean", "description": "是否显式确认执行"},
        }, "required": ["path"]}
    async def execute(self, path: str) -> str:
        # H2：删除必须走 safe_delete —— 先归档保险库副本，再移入回收站，杜绝永久硬删。
        safe_path = _resolve_allowed_path(path)
        try:
            _send_to_recycle_bin(safe_path)
        except FileNotFoundError:
            return f"文件不存在：{safe_path}"
        except RuntimeError as exc:
            return str(exc)
        return f"已删除并归档副本到保险库：{safe_path}"


class ListDirectoryTool(Tool):
    @property
    def name(self) -> str: return "list_directory"
    @property
    def description(self) -> str: return "列出目录下所有文件和子目录"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.fs_query"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string", "description": "目录绝对路径"}}, "required": ["path"]}
    async def execute(self, path: str) -> str:
        safe_path = _resolve_allowed_path(path)
        items = os.listdir(safe_path)
        files, dirs = [], []
        for item in items:
            full = os.path.join(safe_path, item)
            (dirs if os.path.isdir(full) else files).append(item)
        listing_text = f"📁 {len(dirs)} 目录 | 📄 {len(files)} 文件\n"
        if dirs: listing_text += f"\n目录:\n" + "\n".join(f"  📁 {d}" for d in sorted(dirs))
        if files: listing_text += f"\n文件:\n" + "\n".join(f"  📄 {f}" for f in sorted(files))
        return listing_text


class GetFileInfoTool(Tool):
    @property
    def name(self) -> str: return "get_file_info"
    @property
    def description(self) -> str: return "获取文件大小、修改时间等元信息"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.fs_query"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    async def execute(self, path: str) -> str:
        import time
        safe_path = _resolve_allowed_path(path)
        stat = os.stat(safe_path)
        size = stat.st_size
        size_str = f"{size}B" if size < 1024 else f"{size/1024:.1f}KB" if size < 1048576 else f"{size/1048576:.1f}MB" if size < 1073741824 else f"{size/1073741824:.1f}GB"
        return json.dumps({
            "path": safe_path, "size": size_str, "bytes": size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        }, ensure_ascii=False, indent=2)


class SearchFilesTool(Tool):
    @property
    def name(self) -> str: return "search_files"
    @property
    def description(self) -> str: return "按文件名关键词搜索文件"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.fs_query"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"root": {"type": "string"}, "keyword": {"type": "string"}, "max_results": {"type": "integer", "default": 20}}, "required": ["root", "keyword"]}
    async def execute(self, root: str, keyword: str, max_results: int = 20) -> str:
        safe_root = _resolve_allowed_path(root)
        matches = []
        for dirpath, _, filenames in os.walk(safe_root):
            for f in filenames:
                if keyword.lower() in f.lower():
                    matches.append(os.path.join(dirpath, f))
                    if len(matches) >= max_results: break
            if len(matches) >= max_results: break
        return f"找到 {len(matches)} 个文件:\n" + "\n".join(matches) if matches else "未找到匹配文件"


class FileHashTool(Tool):
    @property
    def name(self) -> str: return "file_hash"
    @property
    def description(self) -> str: return "计算文件的 MD5/SHA256 哈希值"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.fs_query"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}, "algorithm": {"type": "string", "enum": ["md5", "sha256"], "default": "sha256"}}, "required": ["path"]}
    async def execute(self, path: str, algorithm: str = "sha256") -> str:
        safe_path = _resolve_allowed_path(path)
        h = hashlib.md5() if algorithm == "md5" else hashlib.sha256()
        with open(safe_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""): h.update(chunk)
        return f"{algorithm.upper()}: {h.hexdigest()}"


class CreateDirectoryTool(Tool):
    @property
    def name(self) -> str: return "create_directory"
    @property
    def description(self) -> str: return "创建目录（含父目录）"
    @property
    def event_type(self) -> str: return "file.read"
    @property
    def tool_permission(self) -> str: return "file.fs_query"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    async def execute(self, path: str) -> str:
        safe_path = _resolve_allowed_path(path)
        Path(safe_path).mkdir(parents=True, exist_ok=True)
        return f"已创建目录 {safe_path}"


FILE_TOOLS = [
    ReadFileTool, WriteFileTool, AppendFileTool, CopyFileTool,
    MoveFileTool, DeleteFileTool, ListDirectoryTool, GetFileInfoTool,
    SearchFilesTool, FileHashTool, CreateDirectoryTool,
]