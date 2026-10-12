# -*- coding: utf-8 -*-
"""打包 1_Demo_LLM 项目更改内容 + 记忆（排除模型/大文件/缓存）"""
import os, sys, zipfile, glob

ROOT = r"D:\P.A.L.M\1_Demo_LLM"
OUT = os.path.join(ROOT, "1_Demo_LLM_更改与记忆_20260924.zip")

# 显式包含清单（= git untracked 12 项 + LLM内核两份新文档 + 引脚图）
INCLUDE = [
    ".workbuddy",
    "ASR对比试验",
    "STT内核",
    "llm_benchmark",
    "人格引擎",
    "加解密内核",
    "桌宠",
    "缝合引擎",
    "记忆",
    "内核API引脚图_v1.0.html",
    os.path.join("LLM内核", "docs", "API对外接口表与用例_v1.0.md"),
    os.path.join("LLM内核", "docs", "内核内部组件与依赖地图_v1.0.md"),
]

# 排除：模型/大文件（用户指定"模型无需"）+ 缓存
EXCLUDE_EXACT = {
    os.path.normpath(os.path.join("桌宠", "live2d_pet", "assets", "whale3d", "whale.glb")),
}
EXCLUDE_DIRS = {"__pycache__", ".git"}

def excluded(rel):
    p = os.path.normpath(rel)
    if p in EXCLUDE_EXACT:
        return True
    if os.path.basename(p) == "__pycache__":
        return True
    if p.endswith(".pyc"):
        return True
    # 缝合引擎的 stitching_vectors_*.npy（91M 模型产物）
    if "stitching_vectors_" in os.path.basename(p) and p.endswith(".npy"):
        return True
    return False

def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    n_files, total = 0, 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in INCLUDE:
            src = os.path.join(ROOT, item)
            if not os.path.exists(src):
                print("[MISS]", item); continue
            if os.path.isfile(src):
                rel = item
                zf.write(src, os.path.join("1_Demo_LLM", rel))
                n_files += 1; total += os.path.getsize(src)
                continue
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, ROOT)
                    if excluded(rel):
                        print("[SKIP]", rel); continue
                    zf.write(full, os.path.join("1_Demo_LLM", rel))
                    n_files += 1; total += os.path.getsize(full)
    zsize = os.path.getsize(OUT)
    print("files=%d  raw=%.1f MB  zip=%.1f MB" % (n_files, total/1048576, zsize/1048576))
    print("OUT:", OUT)

if __name__ == "__main__":
    sys.exit(main())
