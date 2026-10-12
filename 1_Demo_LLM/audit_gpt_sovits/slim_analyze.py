"""GPT-SoVITS 裁剪可行性分析：import 可达性 BFS。

只做静态分析，不移动/删除任何文件。
用法: python slim_analyze.py <root> [--entries a.py,b.py] [--json out.json]
"""
import ast
import json
import os
import sys
from collections import defaultdict

# 注意：不要把 "models" / "module" 这类通用名放进 SKIP_DIRS —— 会误伤 GPT_SoVITS/AR/models
# 等源码包（实测踩过：AR/models 整包被跳过，导致 AR 模块全部误判为不可达）。
# 权重目录按"根级路径"单独排除，见 build_skip_abs()。
SKIP_DIRS = {"runtime", "pretrained_models", "__pycache__", ".git", "node_modules",
             "uvr5_weights", "custom_refs", "cache", "outputs", "runtime_logs"}

PROJECT_PY = []  # 由 main() 填充，供模块名唯一同名消歧

# sys.path 里可能被塞进来的根目录（GPT-SoVITS 运行时常见做法）
EXTRA_ROOTS = ["GPT_SoVITS", "tools", "."]


def iter_py(root):
    skip_abs = {os.path.abspath(os.path.join(root, d))
                for d in ("models", "pretrained_models", "runtime", "7-Zip", "Aria2")}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and os.path.abspath(os.path.join(dirpath, d)) not in skip_abs]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def rel(root, p):
    return os.path.relpath(p, root).replace("\\", "/")


def mod2path(root, modname, from_file=None):
    """模块名 -> 文件路径。返回 (path, kind)，kind in {pkg, mod, None}。"""
    parts = modname.split(".")
    cands = []
    if from_file is not None:
        # 相对包根解析（处理 sys.path 含子目录的情况）
        cands.append(os.path.dirname(from_file))
    for r in EXTRA_ROOTS:
        cands.append(os.path.join(root, r))
    cands.append(root)
    for base in cands:
        p = os.path.join(base, *parts) + ".py"
        if os.path.isfile(p):
            return os.path.abspath(p), "mod"
        p = os.path.join(base, *parts, "__init__.py")
        if os.path.isfile(p):
            return os.path.abspath(p), "pkg"
    # 兜底：项目内唯一同名 .py（处理 sys.path.append 子目录后的裸模块名导入）
    tail = parts[-1] + ".py" if parts else None
    if tail:
        hits = [f for f in PROJECT_PY if os.path.basename(f) == tail]
        if len(hits) == 1:
            return hits[0], "mod"
    return None, None


def resolve_relative(root, from_file, level, modname):
    """解析 from ..X import Y 相对导入。"""
    d = os.path.dirname(from_file)
    # level=1 → 当前包目录就是 d；level=2 → 上提一级；依此类推
    for _ in range(level - 1):
        d = os.path.dirname(d)
    base = d
    parts = modname.split(".") if modname else []
    p = os.path.join(base, *parts) + ".py"
    if os.path.isfile(p):
        return os.path.abspath(p), "mod"
    p = os.path.join(base, *parts, "__init__.py")
    if os.path.isfile(p):
        return os.path.abspath(p), "pkg"
    return None, None


def parse_imports(path):
    """返回 (deps: list[(modname_or_rel, level)], dynamic: bool, is_import_all: bool)"""
    deps, dynamic = [], False
    try:
        src = open(path, "r", encoding="utf-8", errors="replace").read()
        tree = ast.parse(src)
    except Exception:
        return deps, True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                deps.append((a.name, 0))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                if node.module:
                    deps.append((node.module, node.level))
                else:
                    # `from . import X` / `from .. import X`：子模块名在 names 里
                    for a in node.names:
                        deps.append((a.name, node.level))
            elif node.module:
                deps.append((node.module, 0))
        elif isinstance(node, ast.Call):
            f = node.func
            nm = getattr(f, "id", None) or getattr(f, "attr", None)
            if nm in ("__import__", "import_module", "load_module", "exec_module",
                      "spec_from_file_location", "SourceFileLoader"):
                dynamic = True
    return deps, dynamic


def main():
    root = os.path.abspath(sys.argv[1])
    entries = sys.argv[sys.argv.index("--entries") + 1].split(",") if "--entries" in sys.argv else []
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None

    files = [os.path.abspath(p) for p in iter_py(root)]

    # 运行时 sys.path 可能被塞进任意子目录（如 sv.py 塞 GPT_SoVITS/eres2net）
    # ⇒ 把所有含 .py 的目录都作为候选解析根，并用"唯一同名"消歧
    global EXTRA_ROOTS, PROJECT_PY
    PROJECT_PY = files
    EXTRA_ROOTS = EXTRA_ROOTS + sorted({os.path.dirname(f) for f in files})

    graph = defaultdict(set)
    dynamic_files = set()
    unresolved = defaultdict(set)

    for f in files:
        deps, dyn = parse_imports(f)
        if dyn:
            dynamic_files.add(f)
        for modname, level in deps:
            if level:
                tgt, kind = resolve_relative(root, f, level, modname)
            else:
                tgt, kind = mod2path(root, modname, f)
            if tgt:
                graph[f].add(tgt)
                if kind == "pkg":
                    # 导入包：其 __init__ 可能再导入子模块，已由 __init__ 自身边覆盖
                    pass
            else:
                top = modname.split(".")[0]
                # 只登记"看起来像本项目模块"的未解析项，排除第三方/stdlib
                local_tops = {"GPT_SoVITS", "AR", "BigVGAN", "module", "text", "tools", "sv",
                              "process_ckpt", "TTS_infer_pack", "feature_extractor", "eres2net",
                              "f5_tts", "inference_webui", "utils", "configs"}
                if top in local_tops:
                    unresolved[top].add(rel(root, f) + " :: " + modname)

    # 动态导入的文件：保守起见，把同目录所有 py 视为可达
    dyn_closure = set()
    for f in dynamic_files:
        for sib in iter_py(os.path.dirname(f)):
            dyn_closure.add(os.path.abspath(sib))

    entry_files = set()
    for e in entries:
        p = e if os.path.isabs(e) else os.path.join(root, e)
        p = os.path.abspath(p)
        if os.path.isfile(p):
            entry_files.add(p)
        else:
            print("[warn] 入口不存在:", e)

    start = entry_files | dyn_closure
    seen, stack = set(start), list(start)
    while stack:
        cur = stack.pop()
        for nxt in graph.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)

    reachable = seen
    unreachable = [f for f in files if f not in reachable]

    def loc(p):
        try:
            return sum(1 for _ in open(p, "r", encoding="utf-8", errors="replace"))
        except Exception:
            return 0

    res = {
        "root": root,
        "entries": sorted(rel(root, p) for p in entry_files),
        "total_files": len(files),
        "reachable_files": len(reachable),
        "unreachable_files": len(unreachable),
        "unreachable": sorted(
            ({"path": rel(root, f), "loc": loc(f)} for f in unreachable),
            key=lambda d: (-d["loc"], d["path"])),
        "dynamic_files": sorted(rel(root, f) for f in dynamic_files),
        "unresolved_imports": {k: sorted(v) for k, v in unresolved.items()},
    }
    if out_json:
        json.dump(res, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"入口: {res['entries']}")
    print(f"总 py 文件 {len(files)} | 可达 {len(reachable)} | 不可达 {len(unreachable)}")
    print(f"含动态导入的文件 {len(dynamic_files)} 个（已保守把同目录纳入可达）")
    print("\n=== 未解析的项目内 import（需人工确认，误判风险点）===")
    for k, v in sorted(unresolved.items()):
        v = sorted(v)
        print(f"  [{k}] {len(v)} 条，样例: {v[:3]}")

    print("\n=== 不可达文件（可砍候选），按目录聚合 ===")
    agg = defaultdict(lambda: [0, 0])
    for f in unreachable:
        d = os.path.dirname(rel(root, f)) or "."
        agg[d][0] += 1
        agg[d][1] += loc(f)
    for d, (n, l) in sorted(agg.items(), key=lambda x: -x[1][1]):
        print(f"  {l:>6} 行 / {n:>3} 文件   {d}")
    print(f"\n  JSON -> {out_json}" if out_json else "")


if __name__ == "__main__":
    main()
