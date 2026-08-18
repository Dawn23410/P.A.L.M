"""组件包加载与单文件打包：文件夹包 / .pwidget / .html → 统一 (manifest, html)。

三种形式等价：
- 文件夹包：widget.json + index.html + style.css(可选) + script.js(可选)
- .pwidget：单文件。优先 ZIP 容器（manifest.json + 源码 + assets/，可内嵌二进制资源、带压缩）；
  旧版纯文本 JSON（内嵌 manifest/html/css/js）按文件头自动向后兼容。
- .html：自包含 HTML，<meta name="palm-widget"> 携带清单

另提供 pack_widget / unpack_widget 把文件夹组件打包为单文件 .pwidget（或反向解包），
assets/ 下的二进制资源在组装/解包时按 `assets/<相对路径>` 引用内联为 data URI，
使组件在 pywebview 字符串渲染下自包含。

加载失败抛 WidgetLoadError，由宿主捕获并跳过，不影响其他组件。
"""

import base64
import json
import os
import re
import zipfile

from .injector import BASE_STYLE, inject_shim


class WidgetLoadError(Exception):
    """组件包无法解析时抛出。"""


# 后端可下发的全部 provider（零信任：组件须显式声明才放行）。
KNOWN_PROVIDERS = {"time", "system", "cpu", "memory", "disk", "network", "battery", "weather", "audio"}


def build_html(manifest, body_html, css, js):
    """组装 .pwidget / 文件夹包的完整 HTML。"""
    widget_id = manifest.get("id", "widget")
    meta = f'<meta name="palm-widget" content=\'{json.dumps(manifest, ensure_ascii=False)}\'>'
    shim = inject_shim(widget_id)
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>{meta}"
        f"<style>{BASE_STYLE}{css}</style></head><body>"
        f"{body_html}<script>{shim}</script><script>{js}</script></body></html>"
    )


def _extract_manifest(raw_html):
    """从单文件 .html 的 <meta name="palm-widget"> 提取清单。

    清单属性的引号写法不定（单/双引号皆可），故正则对两种引号都兼容。
    """
    match = re.search(
        r'''<meta\s+name\s*=\s*["']palm-widget["']\s+content\s*=\s*["'](.*?)["']\s*/?>''',
        raw_html, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            pass
    return {}


def _inject_into_html(raw_html, manifest):
    """把桥与基座样式注入单文件 .html，保留用户原内容。"""
    widget_id = manifest.get("id", "widget")
    shim = inject_shim(widget_id)
    head = f"<style>{BASE_STYLE}</style>"
    out = raw_html
    if "</head>" in out:
        out = out.replace("</head>", head + "</head>", 1)
    else:
        out = head + out
    if "</body>" in out:
        out = out.replace("</body>", f"<script>{shim}</script></body>", 1)
    else:
        out = out + f"<script>{shim}</script>"
    return out


def _validate_manifest(manifest, source):
    if not isinstance(manifest, dict):
        raise WidgetLoadError(f"{source}: manifest 必须是对象")
    widget_id = manifest.get("id")
    if not widget_id or not isinstance(widget_id, str):
        raise WidgetLoadError(f"{source}: 缺少合法 id 字段")
    manifest["permissions"] = _normalize_permissions(manifest.get("permissions"))
    return manifest


def _normalize_permissions(permissions):
    """收敛权限声明：仅保留已知 provider 或通配 '*'；缺失默认全开（向后兼容）。"""
    if permissions is None:
        return ["*"]
    if not isinstance(permissions, list):
        return ["*"]
    normalized = []
    for item in permissions:
        if item == "*" or (isinstance(item, str) and item in KNOWN_PROVIDERS):
            normalized.append(item)
    return normalized if normalized else ["*"]


def load_widget_package(path):
    """按路径加载组件包，返回 (manifest, html)。失败抛 WidgetLoadError。"""
    if os.path.isdir(path):
        return _load_folder(path)
    if path.endswith(".pwidget"):
        return _load_pwidget(path)
    if path.endswith(".html"):
        return _load_html(path)
    raise WidgetLoadError(f"{path}: 不支持的组件格式")


def _load_folder(path):
    manifest_path = os.path.join(path, "widget.json")
    if not os.path.exists(manifest_path):
        raise WidgetLoadError(f"{path}: 缺少 widget.json")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    _validate_manifest(manifest, path)
    body = _read_optional(os.path.join(path, "index.html"), default="")
    css = _read_optional(os.path.join(path, "style.css"), default="")
    js = _read_optional(os.path.join(path, "script.js"), default="")
    return manifest, build_html(manifest, body, css, js)


def _load_pwidget(path):
    """加载 .pwidget：ZIP 容器（可内嵌二进制资源，推荐）或旧版纯文本 JSON，按文件头识别。"""
    if _is_zip_file(path):
        return _load_pwidget_zip(path)
    with open(path, "r", encoding="utf-8") as fh:
        pkg = json.load(fh)
    manifest = _validate_manifest(pkg.get("manifest", {}), path)
    return manifest, build_html(
        manifest, pkg.get("html", ""), pkg.get("css", ""), pkg.get("js", ""))


def _is_zip_file(path):
    """按文件头 4 字节 PK\\x03\\x04 判断是否为 ZIP 容器（与旧版 JSON 区分）。"""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except OSError:
        return False


_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".bmp": "image/bmp",
    ".woff": "font/woff", ".woff2": "font/woff2",
    ".ttf": "font/ttf", ".otf": "font/otf",
    ".json": "application/json", ".csv": "text/csv", ".txt": "text/plain",
    ".xml": "application/xml", ".wav": "audio/wav", ".mp3": "audio/mpeg",
}


def _guess_mime(filename):
    return _MIME_BY_EXT.get(os.path.splitext(filename)[1].lower(),
                            "application/octet-stream")


def _read_zip_text(zf, name):
    try:
        return zf.read(name).decode("utf-8")
    except KeyError:
        return ""


def _inline_assets(text, assets):
    """把文本里的 `assets/<相对路径>` 引用替换为内联 data URI。"""
    if not assets:
        return text
    # 仅捕获相对路径作为 group(1)，供查表替换为 data URI。
    pattern = re.compile(
        r"assets/(" + "|".join(re.escape(r) for r in assets) + r")")
    return pattern.sub(lambda m: assets[m.group(1)], text)


def _load_pwidget_zip(path):
    """ZIP 容器式 .pwidget：manifest.json + index.html + style.css + script.js + assets/*。

    assets/ 下资源在组装 HTML 时按引用内联为 data URI，使组件在 pywebview 字符串
    渲染下也能自包含（无需运行时资源服务器）。
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                raise WidgetLoadError(f"{path}: ZIP 缺少 manifest.json")
            manifest = _validate_manifest(
                json.loads(zf.read("manifest.json").decode("utf-8")), path)
            html = _read_zip_text(zf, "index.html")
            css = _read_zip_text(zf, "style.css")
            js = _read_zip_text(zf, "script.js")
            assets = {}
            for n in names:
                if n.startswith("assets/") and not n.endswith("/"):
                    rel = n[len("assets/"):]
                    b64 = base64.b64encode(zf.read(n)).decode("ascii")
                    assets[rel] = f"data:{_guess_mime(n)};base64,{b64}"
    except zipfile.BadZipFile as exc:
        raise WidgetLoadError(f"{path}: 不是合法 ZIP：{exc}")
    html = _inline_assets(html, assets)
    css = _inline_assets(css, assets)
    return manifest, build_html(manifest, html, css, js)


def _load_html(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    manifest = _extract_manifest(raw)
    _validate_manifest(manifest, path)
    return manifest, _inject_into_html(raw, manifest)


def _read_optional(path, default=""):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return default


def split_widget_source(path):
    """读取组件源码供编辑器使用，返回 {type, html, css, js, raw}。"""
    if os.path.isdir(path):
        return {
            "type": "folder",
            "html": _read_optional(os.path.join(path, "index.html")),
            "css": _read_optional(os.path.join(path, "style.css")),
            "js": _read_optional(os.path.join(path, "script.js")),
        }
    if path.endswith(".pwidget"):
        if _is_zip_file(path):
            with zipfile.ZipFile(path, "r") as zf:
                return {
                    "type": "pwidget",
                    "html": _read_zip_text(zf, "index.html"),
                    "css": _read_zip_text(zf, "style.css"),
                    "js": _read_zip_text(zf, "script.js"),
                }
        with open(path, "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
        return {
            "type": "pwidget",
            "html": pkg.get("html", ""),
            "css": pkg.get("css", ""),
            "js": pkg.get("js", ""),
        }
    if path.endswith(".html"):
        with open(path, "r", encoding="utf-8") as fh:
            return {"type": "html", "raw": fh.read()}
    raise WidgetLoadError(f"{path}: 不支持的组件格式")


def _write_if_dir(path, name, content):
    """文件夹包：仅当文件已存在或内容非空才写，避免凭空新增空文件。"""
    fp = os.path.join(path, name)
    if os.path.exists(fp) or content:
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(content)


def write_widget_source(path, source):
    """把编辑器内容写回组件文件；pwidget 保留 manifest 其余字段。"""
    src_type = source.get("type")
    if src_type == "pwidget":
        if _is_zip_file(path):
            _write_pwidget_zip(path, source)
        else:
            with open(path, "r", encoding="utf-8") as fh:
                pkg = json.load(fh)
            pkg["html"] = source.get("html", "")
            pkg["css"] = source.get("css", "")
            pkg["js"] = source.get("js", "")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(pkg, fh, ensure_ascii=False, indent=2)
    elif src_type == "folder":
        _write_if_dir(path, "index.html", source.get("html", ""))
        _write_if_dir(path, "style.css", source.get("css", ""))
        _write_if_dir(path, "script.js", source.get("js", ""))
    elif src_type == "html":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source.get("raw", ""))
    else:
        raise WidgetLoadError(f"未知源码类型：{src_type}")


def _write_pwidget_zip(path, source):
    """重写 ZIP 式 pwidget 的三段文本，保留 manifest.json 与 assets/*。"""
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        if "manifest.json" not in names:
            raise WidgetLoadError(f"{path}: ZIP 缺少 manifest.json")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        # 资产键仅保留相对路径，_write_pwidget_zip_file 会统一加 assets/ 前缀。
        asset_items = {}
        for n in names:
            if n.startswith("assets/") and not n.endswith("/"):
                asset_items[n[len("assets/"):]] = zf.read(n)
    _write_pwidget_zip_file(
        path, manifest,
        source.get("html", ""), source.get("css", ""), source.get("js", ""),
        asset_items)


def _collect_assets(asset_dir):
    """收集 <asset_dir> 下全部文件为 {相对路径: bytes}。"""
    assets = {}
    if not os.path.isdir(asset_dir):
        return assets
    for root, _dirs, files in os.walk(asset_dir):
        for name in files:
            fp = os.path.join(root, name)
            rel = os.path.relpath(fp, asset_dir).replace(os.sep, "/")
            with open(fp, "rb") as fh:
                assets[rel] = fh.read()
    return assets


def _write_pwidget_zip_file(out_path, manifest, html, css, js, assets):
    """把 manifest + 三段文本 + assets 落盘为 ZIP 式 .pwidget。"""
    entries = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
        "index.html": html,
        "style.css": css,
        "script.js": js,
    }
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            if content or name == "manifest.json":
                zf.writestr(name, content)
        for rel, data in assets.items():
            zf.writestr("assets/" + rel, data)


def pack_widget(src, out_path, *, asset_dir="assets"):
    """把文件夹组件（或旧版 JSON .pwidget）打包成单文件 ZIP 式 .pwidget。

    - 文件夹源：读 widget.json(manifest) + index.html/style.css/script.js(可选)
      + <asset_dir>/(可选)，写入 ZIP。
    - 旧版 JSON .pwidget 源：1:1 转写为 ZIP 容器。
    约定：HTML/CSS 内以 `assets/<相对路径>` 引用资源，加载时自动内联为 data URI。
    """
    if os.path.isdir(src):
        manifest_path = os.path.join(src, "widget.json")
        if not os.path.exists(manifest_path):
            raise WidgetLoadError(f"{src}: 缺少 widget.json")
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        _validate_manifest(manifest, src)
        html = _read_optional(os.path.join(src, "index.html"))
        css = _read_optional(os.path.join(src, "style.css"))
        js = _read_optional(os.path.join(src, "script.js"))
        assets = _collect_assets(os.path.join(src, asset_dir))
    elif src.endswith(".pwidget") and not _is_zip_file(src):
        with open(src, "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
        manifest = _validate_manifest(pkg.get("manifest", {}), src)
        html, css, js = pkg.get("html", ""), pkg.get("css", ""), pkg.get("js", "")
        assets = {}
    else:
        raise WidgetLoadError(f"{src}: 仅支持文件夹或旧版 JSON .pwidget 作为打包源")
    _write_pwidget_zip_file(out_path, manifest, html, css, js, assets)
    return out_path


def unpack_widget(pwidget_path, out_dir):
    """把 .pwidget 解包为文件夹组件（manifest.json→widget.json，资源内联进 HTML/CSS）。

    解包时把 assets/ 内联为 data URI 写进 index.html/style.css，使得到的文件夹组件
    自包含、可直接被 _load_folder 加载（无需文件夹级资源解析）。
    """
    if _is_zip_file(pwidget_path):
        with zipfile.ZipFile(pwidget_path, "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise WidgetLoadError(f"{pwidget_path}: ZIP 缺少 manifest.json")
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            html = _read_zip_text(zf, "index.html")
            css = _read_zip_text(zf, "style.css")
            js = _read_zip_text(zf, "script.js")
            assets = {}
            for n in names:
                if n.startswith("assets/") and not n.endswith("/"):
                    rel = n[len("assets/"):]
                    b64 = base64.b64encode(zf.read(n)).decode("ascii")
                    assets[rel] = f"data:{_guess_mime(n)};base64,{b64}"
        html = _inline_assets(html, assets)
        css = _inline_assets(css, assets)
    else:
        with open(pwidget_path, "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
        manifest = pkg.get("manifest", {})
        html, css, js = pkg.get("html", ""), pkg.get("css", ""), pkg.get("js", "")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "widget.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    _write_if_dir(out_dir, "index.html", html)
    _write_if_dir(out_dir, "style.css", css)
    _write_if_dir(out_dir, "script.js", js)
    return out_dir


def peek_manifest(pwidget_path):
    """读取 .pwidget 的 manifest（用于安装时取组件 id），不组装 HTML。"""
    if _is_zip_file(pwidget_path):
        with zipfile.ZipFile(pwidget_path, "r") as zf:
            return json.loads(zf.read("manifest.json").decode("utf-8"))
    with open(pwidget_path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("manifest", {})
