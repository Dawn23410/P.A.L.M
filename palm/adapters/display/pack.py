"""桌面组件单文件打包 / 解包命令行工具。

把文件夹组件（或旧版 JSON .pwidget）打包成单个 .pwidget（ZIP 容器，可内嵌二进制资源），
或把 .pwidget 反向解包为文件夹组件。

用法：
  python pack.py pack   <src文件夹|旧版JSON> <out.pwidget>
  python pack.py unpack <in.pwidget> <out文件夹>
  python pack.py unpack <in.pwidget> --install        # 直接解包安装到 widget_demo/widgets/<id>/
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .loader import pack_widget, unpack_widget, peek_manifest, WidgetLoadError

WIDGETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widgets")


def _cmd_pack(args):
    pack_widget(args.src, args.out)
    print(f"已打包 → {args.out}")


def _cmd_unpack(args):
    if args.install:
        manifest = peek_manifest(args.src)
        wid = manifest.get("id")
        if not wid:
            print("错误：清单缺少 id，无法安装")
            sys.exit(1)
        out = os.path.join(WIDGETS_DIR, wid)
        if os.path.exists(out):
            print(f"错误：目标已存在 {out}（先移除再安装）")
            sys.exit(1)
    else:
        out = args.out
    unpack_widget(args.src, out)
    print(f"已解包 → {out}")


def main():
    ap = argparse.ArgumentParser(
        description="桌面组件单文件 .pwidget 打包 / 解包工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="文件夹/旧版JSON → 单文件 .pwidget")
    p.add_argument("src", help="组件文件夹 或 旧版 JSON .pwidget")
    p.add_argument("out", help="输出 .pwidget 路径")
    p.set_defaults(func=_cmd_pack)

    u = sub.add_parser("unpack", help="单文件 .pwidget → 文件夹组件")
    u.add_argument("src", help="输入 .pwidget")
    u.add_argument("out", nargs="?", default=".", help="输出文件夹（install 时忽略）")
    u.add_argument("--install", action="store_true",
                   help="直接解包安装到 widget_demo/widgets/<id>/")
    u.set_defaults(func=_cmd_unpack)

    args = ap.parse_args()
    try:
        args.func(args)
    except WidgetLoadError as exc:
        print(f"错误：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
