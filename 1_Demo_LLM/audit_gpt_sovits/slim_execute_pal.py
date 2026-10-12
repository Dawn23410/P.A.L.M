"""P.A.L.M 核心检验区 GSV 裁剪执行器：隔离式（复制到备份 + MD5 校验 + 从原位移除）。

目标: D:/P.A.L.M/核心-检验/语音合成_GPT-SoVITS（palm-chat GSV 生产后端 :10080）
依据: slim_reach_pal.json（静态可达性）× trace_used_pal.json（运行时取证，v4 合成）

用法:
  python slim_execute_pal.py --plan          # 只打印计划，不动任何文件
  python slim_execute_pal.py --run           # 执行（复制→校验→移除）
  python slim_execute_pal.py --rollback      # 把备份整体拷回原位（已存在则跳过）
"""
import hashlib
import json
import os
import shutil
import sys

ROOT = "D:/P.A.L.M/核心-检验/语音合成_GPT-SoVITS"
BACKUP = "D:/P.A.L.M/1_Demo_LLM/.workbuddy/backup/20260927_gsv_pal_slim"
REACH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slim_reach_pal.json")

# 删除单元（dir=整目录 / file=单文件），按批组织；每批执行后必须跑一次冒烟
BATCHES = [
    ("批1 训练脚本与数据集", [
        ("dir", "GPT_SoVITS/prepare_datasets"),
        ("file", "GPT_SoVITS/s1_train.py"),
        ("file", "GPT_SoVITS/s2_train.py"),
        ("file", "GPT_SoVITS/s2_train_v3.py"),
        ("file", "GPT_SoVITS/s2_train_v3_lora.py"),
        ("file", "GPT_SoVITS/train_cli.py"),
        ("file", "GPT_SoVITS/train_util.py"),
        ("file", "GPT_SoVITS/download.py"),
    ]),
    ("批2 导出与 ONNX 变体", [
        ("file", "GPT_SoVITS/onnx_export.py"),
        ("file", "GPT_SoVITS/export_torch_script.py"),
        ("file", "GPT_SoVITS/export_torch_script_v3v4.py"),
        ("file", "GPT_SoVITS/module/models_onnx.py"),
        ("file", "GPT_SoVITS/module/data_utils.py"),
        ("file", "GPT_SoVITS/module/attentions_onnx.py"),
        ("file", "GPT_SoVITS/module/losses.py"),
    ]),
    ("批3 AR 训练侧与 ONNX 变体", [
        ("dir", "GPT_SoVITS/AR/data"),
        ("dir", "GPT_SoVITS/AR/text_processing"),
        ("file", "GPT_SoVITS/AR/utils/initialize.py"),  # io.py 可达 + __init__.py 保留（父包含可达件）
        ("file", "GPT_SoVITS/AR/models/t2s_model_onnx.py"),
        ("file", "GPT_SoVITS/AR/models/t2s_lightning_module_onnx.py"),
        ("file", "GPT_SoVITS/AR/modules/transformer_onnx.py"),
        ("file", "GPT_SoVITS/AR/modules/activation_onnx.py"),
        ("file", "GPT_SoVITS/AR/modules/patched_mha_with_cache_onnx.py"),
        ("file", "GPT_SoVITS/AR/modules/embedding_onnx.py"),
    ]),
    ("批4 BigVGAN 冗余", [
        ("file", "GPT_SoVITS/BigVGAN/train.py"),
        ("file", "GPT_SoVITS/BigVGAN/discriminators.py"),
        ("file", "GPT_SoVITS/BigVGAN/loss.py"),
        ("file", "GPT_SoVITS/BigVGAN/inference.py"),
        ("file", "GPT_SoVITS/BigVGAN/inference_e2e.py"),
        ("dir", "GPT_SoVITS/BigVGAN/tests"),
        ("file", "GPT_SoVITS/BigVGAN/alias_free_activation/cuda/load.py"),
        # 用户约束：所有版本底模及其代码全保留（v2/v3/v4/v2Pro/v2ProPlus）
        # => eres2net 全目录、f5_tts 全目录、pretrained_models 全部权重不动
    ]),
    ("批5 GUI 与入口", [
        ("file", "webui.py"),
        ("file", "GPT_SoVITS/inference_webui_fast.py"),
        ("file", "GPT_SoVITS/inference_gui.py"),
    ]),
    ("批6 tools 数据预处理", [
        ("dir", "tools/uvr5"),
        ("file", "tools/slicer2.py"),
        ("file", "tools/slice_audio.py"),
        ("file", "tools/cmd-denoise.py"),
        ("file", "tools/subfix_webui.py"),
        ("file", "tools/my_infer.py"),
        ("file", "tools/my_utils.py"),
        ("file", "tools/i18n/scan_i18n.py"),
    ]),
    ("批7 ASR", [
        ("dir", "tools/asr"),
    ]),
]


# 人工确认白名单：非 .py 但已确认可删
MANUAL_ALLOW = set()


def units():
    for _, us in BATCHES:
        for u in us:
            yield u


def iter_target_files(kind, rel):
    ap = os.path.join(ROOT, rel.replace("/", os.sep))
    if kind == "file":
        yield ap, rel
        return
    for dp, dn, fn in os.walk(ap):
        dn[:] = [x for x in dn if x != "__pycache__"]
        for f in fn:
            fp = os.path.join(dp, f)
            yield fp, os.path.relpath(fp, ROOT).replace("\\", "/")


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan():
    d = json.load(open(REACH, encoding="utf-8"))
    un = {x["path"]: x["loc"] for x in d["unreachable"]}
    total_files = total_loc = 0
    for name, us in BATCHES:
        nf = nl = 0
        for kind, rel in us:
            if not os.path.exists(os.path.join(ROOT, rel.replace("/", os.sep))):
                print(f"  [warn] {name}: {rel} 不存在（可能已移除）")
                continue
            for _, r in iter_target_files(kind, rel):
                nf += 1
                nl += un.get(r, 0)
        print(f"  {name}: {nf} 个文件 / {nl} 行")
        total_files += nf
        total_loc += nl
    print(f"\n  合计 {total_files} 个文件 / {total_loc} 行 -> {BACKUP}")


def run():
    d = json.load(open(REACH, encoding="utf-8"))
    un = {x["path"] for x in d["unreachable"]}
    report = {"batches": [], "restored_needed": []}
    for name, us in BATCHES:
        done, failed = [], []
        for kind, rel in us:
            src_root = os.path.join(ROOT, rel.replace("/", os.sep))
            if not os.path.exists(src_root):
                continue
            ok = True
            # 先逐文件复制到备份
            for ap, r in iter_target_files(kind, rel):
                # 整目录删除语义：只对 .py 源码逐一核对不可达清单；权重/资源随目录走
                if r.endswith(".py") and r not in un and r not in MANUAL_ALLOW:
                    print(f"  [SKIP] {r} 不在不可达清单，防止误删")
                    ok = False
                    break
                dst = os.path.join(BACKUP, r.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(ap, dst)
                if md5(ap) != md5(dst):
                    print(f"  [MD5 不一致] {r}")
                    ok = False
                    break
            # 校验通过才从原位移除
            if ok:
                shutil.rmtree(src_root) if os.path.isdir(src_root) else os.remove(src_root)
                done.append(rel)
            else:
                failed.append(rel)
        print(f"{name}: 移除 {len(done)} / 失败中止 {len(failed)} {failed}")
        report["batches"].append({"name": name, "removed": done, "failed": failed})
        if failed:
            print("  有失败单元，停止后续批次，请先处理")
            break
    json.dump(report, open(os.path.join(os.path.dirname(REACH), "slim_exec_report_pal.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rollback():
    if not os.path.isdir(BACKUP):
        print("备份目录不存在:", BACKUP)
        return
    n = 0
    for dp, dn, fn in os.walk(BACKUP):
        for f in fn:
            src = os.path.join(dp, f)
            rel = os.path.relpath(src, BACKUP)
            dst = os.path.join(ROOT, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                n += 1
    print(f"已回滚 {n} 个文件（已存在的未覆盖）")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--plan"
    {"--plan": plan, "--run": run, "--rollback": rollback}[mode]()
