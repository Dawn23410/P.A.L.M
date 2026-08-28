"""GUI 世界模型·动态认知 Atlas 的数据模型与判定规则。

定义 software_id 派生、level_id 派生、节点 identity、静态/动态分类。
Atlas 只描述"有什么 UI"，绝不存任何运行态值（开关 on/off、状态文本、列表内容、计数、编辑文本）。
"""
from __future__ import annotations

import hashlib
import re

# Atlas 在 storage 砖中的分类名（经 capability 落盘，受配额/生命周期管理）。
ATLAS_CATEGORY = "gui_atlas"
ATLAS_VERSION = 1

# exe 镜像名 → 稳定 software_id（归一化，避免按易变标题区分软件）。
_EXE_TO_SOFTWARE = {
    "devenv.exe": "visual_studio",
    "notepad.exe": "notepad",
    "notepad++.exe": "notepad_plus_plus",
    "code.exe": "vscode",
    "systemsettings.exe": "windows_settings",
    "control.exe": "control_panel",
    "explorer.exe": "file_explorer",
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "firefox.exe": "firefox",
    "excel.exe": "excel",
    "winword.exe": "word",
    "powerpnt.exe": "powerpoint",
}

# 动态内容线索：命中即视为"会变的值"，只标占位不存具体值。
_DYNAMIC_HINT_RE = re.compile(
    r"(%|\d{1,3}:\d{1,3}|\d{4}[-/年.]\d{1,2}([-/月.]\d{1,2})?|"
    r"https?://|\\|/[a-z]:|[A-Za-z]:\\|\b\d+\s*(个|项|条|首|封)?\b)"
)

# 开关类控件：其"开/关"态禁止持久化，仅存开关存在 + 静态标签。
_TOGGLE_TYPES = {"Toggle", "CheckBox", "Switch", "RadioButton"}

# 内容型控件：name 通常是用户内容/文档，动态不存值（Text 不在内，交由下方 status/text 分支处理）。
_CONTENT_TYPES = {"Edit", "Document"}

# 导航候选容器类型（其直接子节点多为导航项）。
_NAV_CONTAINER_TYPES = {"Tree", "List", "Tab", "Group", "Pane", "SemanticZoom"}


def normalize_exe(exe: str) -> str:
    """exe 镜像名 → 稳定 software_id；未知则去扩展名小写兜底。"""
    name = (exe or "").strip().lower()
    if not name:
        return "unknown"
    if name in _EXE_TO_SOFTWARE:
        return _EXE_TO_SOFTWARE[name]
    if name.endswith(".exe"):
        name = name[:-4]
    return re.sub(r"[^a-z0-9_]+", "_", name) or "unknown"


def is_static_label(name: str) -> bool:
    """判断控件名是否为稳定静态标签（非计数/状态/路径/时间等会变的值）。"""
    if not name or not name.strip():
        return False
    # 图标字体（PUA 私用区）不是文本标签，忽略。
    if any("\ue000" <= ch <= "\uf8ff" for ch in name):
        return False
    if _DYNAMIC_HINT_RE.search(name):
        return False
    if len(name) > 40:
        return False
    return True


def classify_node(control_type: str, name: str) -> tuple[str, dict | None]:
    """归纳节点 role 与动态占位。

    control_type 在 UIA 中带 "Control" 后缀（如 TextControl），先归一化再去匹配。
    返回 (role, dynamic)：dynamic 为 None 表示纯静态；否则为
    {kind:"variable", reason:...} 占位（绝不存具体值）。toggle 的静态标签仍保留，
    仅其开/关态不存。
    """
    control_type = control_type.removesuffix("Control")
    if control_type in _TOGGLE_TYPES:
        # 开关存在可记，但其开/关态禁止持久化。
        return "toggle", {"kind": "variable", "reason": "toggle_state"}
    if control_type in _CONTENT_TYPES:
        # 编辑框/文档/文本：name 通常是内容，动态不存。
        return "editor", {"kind": "variable", "reason": "edited_text"}
    if control_type in {"StatusBar", "AppBar", "Text"}:
        # 这类文本控件天生显示状态/信息，默认值会变，仅标占位不存具体值。
        return "status", {"kind": "variable", "reason": "status_text"}
    if control_type in {"List", "ListBox", "DataGrid", "Table"}:
        # 列表容器静态，其条目内容动态（数量/条目不存）。
        dyn = {"kind": "variable", "reason": "list_content"} if (name and not is_static_label(name)) else None
        return "list", dyn
    if control_type in {"ListItem", "TreeItem"}:
        # 导航项（设置左侧栏/资源管理器树）：静态标签保留供规划引用，动态命名才标占位。
        dyn = {"kind": "variable", "reason": "status_text"} if (name and not is_static_label(name)) else None
        return "nav", dyn
    role = {
        "Button": "button", "MenuItem": "menu", "MenuBar": "menubar",
        "TabItem": "tab", "Hyperlink": "link", "ComboBox": "combobox",
        "Pane": "container", "Group": "container", "Window": "window",
        "Image": "image", "Slider": "slider",
    }.get(control_type, "control")
    dyn = None
    if name and not is_static_label(name):
        # 带动态线索的命名控件（如计数器标题）→ 标 variable，name 不存值。
        dyn = {"kind": "variable", "reason": "status_text"}
    return role, dyn


def node_identity(path: list[tuple[str, str, int]]) -> str:
    """由 (control_type, automation_id, 兄弟序号) 路径生成稳定 identity。"""
    parts = []
    for ct, aid, idx in path:
        parts.append(f"{ct}[{aid if aid else '#' + str(idx)}]")
    return "/".join(parts)


def _collect_nav_items(node: dict, depth: int = 0) -> list[tuple[str, bool]]:
    """递归找导航候选容器，收集其静态命名子项（含选中态）作为导航项。"""
    ct = node.get("control_type", "").removesuffix("Control")
    children = node.get("children", []) or []
    if ct in _NAV_CONTAINER_TYPES and 3 <= len(children) <= 60:
        nav_like = [
            (c.get("name", ""), bool(c.get("selected", False))) for c in children
            if c.get("control_type") in {"ListItem", "TreeItem", "TabItem", "Button", "Hyperlink"}
            and is_static_label(c.get("name", ""))
        ]
        if len(nav_like) >= 3:
            return nav_like
    items: list[tuple[str, bool]] = []
    for c in children:
        items.extend(_collect_nav_items(c, depth + 1))
    return items


def _structure_signature(node: dict) -> str:
    """结构签名兜底：控件类型序列 + 静态名集合的稳定哈希。"""
    blobs: list[str] = []

    def walk(n: dict) -> None:
        blobs.append(n.get("control_type", ""))
        nm = n.get("name", "") or ""
        if is_static_label(nm):
            blobs.append(nm)
        for c in n.get("children", []) or []:
            walk(c)

    walk(node)
    digest = hashlib.sha1("|".join(blobs).encode("utf-8")).hexdigest()
    return digest[:8]


def derive_level_id(tree: dict, title: str) -> tuple[str, str, list[str]]:
    """默认导航启发；找不到导航则回退 single-level(default)。

    返回 (level_id, method, nav_items)。导航启发优先用"被选中"的导航项判定当前页；
    无导航软件（记事本/单文件 VS）统一归 default，不随内容增减分裂层级。
    """
    nav_items = _collect_nav_items(tree)
    if nav_items:
        selected = [n for n, s in nav_items if s]
        if selected:
            return selected[0], "navigation", [n for n, _ in nav_items]
        if title:
            for n, _ in nav_items:
                if n and n in title:
                    return n, "navigation", [n for n, _ in nav_items]
            return nav_items[0][0], "navigation_ambiguous", [n for n, _ in nav_items]
    return "default", "default", []


# ── 语义能力标签（推理中枢的"关键词→控件"映射基础） ──────────
# 意图关键词（中/英）→ 能力标签。控件名命中词库即标注对应能力，
# 使"保存/打开/设置"等意图可纯规则匹配到控件，零 LLM 依赖。
_CAPABILITY_LEXICON = {
    "save": {"保存", "存盘", "存档", "save"},
    "open": {"打开", "开启", "open"},
    "new": {"新建", "新增", "new", "create"},
    "close": {"关闭", "关掉", "close"},
    "settings": {"设置", "选项", "偏好", "settings", "preferences", "option"},
    "delete": {"删除", "移除", "delete", "remove", "trash"},
    "copy": {"复制", "拷贝", "copy"},
    "paste": {"粘贴", "paste"},
    "cut": {"剪切", "cut"},
    "find": {"查找", "搜索", "find", "search", "locate"},
    "undo": {"撤销", "undo"},
    "redo": {"重做", "redo"},
    "back": {"返回", "后退", "back"},
    "next": {"下一步", "前进", "next", "继续"},
    "confirm": {"确认", "确定", "confirm", "ok", "yes"},
    "cancel": {"取消", "cancel"},
    "print": {"打印", "print"},
    "export": {"导出", "export"},
    "import": {"导入", "import"},
    "help": {"帮助", "help"},
    "refresh": {"刷新", "refresh", "reload"},
    "play": {"播放", "play"},
    "pause": {"暂停", "pause"},
    "exit": {"退出", "退出程序", "quit"},
    "select_all": {"全选", "select all"},
    "bold": {"加粗", "bold"},
    "home": {"主页", "首页", "home"},
    "menu": {"菜单", "menu"},
}
_WORD_TO_CAPABILITY = {w: cap for cap, words in _CAPABILITY_LEXICON.items() for w in words}


def derive_capability(name: str, role: str, control_type: str) -> list[str]:
    """由控件名/角色推导语义能力标签（结构性，零 LLM），供推理中枢纯规则匹配。

    角色强信号：开关类天然 toggle、导航/标签类天然 navigate——即便名字不含词库词也能归位。
    """
    tags: list[str] = []
    n = (name or "").strip().lower()
    if n:
        for w, cap in _WORD_TO_CAPABILITY.items():
            if w == n or w in n:
                if cap not in tags:
                    tags.append(cap)
    if role == "toggle" and "toggle" not in tags:
        tags.append("toggle")
    if role in ("tab", "nav") and "navigate" not in tags:
        tags.append("navigate")
    return tags
