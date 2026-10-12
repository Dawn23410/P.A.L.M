"""三档裁剪方案体量核算（只读，不删任何东西）。"""
import json
import os

ROOT = "C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128"
d = json.load(open("slim_reach.json", encoding="utf-8"))
UN = {x["path"]: x["loc"] for x in d["unreachable"]}

# 删除单元：dir=整目录, file=单文件
T1 = [
    ("dir", "GPT_SoVITS/prepare_datasets"),
    ("file", "GPT_SoVITS/s1_train.py"),
    ("file", "GPT_SoVITS/s2_train.py"),
    ("file", "GPT_SoVITS/s2_train_v3.py"),
    ("file", "GPT_SoVITS/s2_train_v3_lora.py"),
    ("file", "GPT_SoVITS/train_cli.py"),
    ("file", "GPT_SoVITS/train_util.py"),
    ("file", "GPT_SoVITS/onnx_export.py"),
    ("file", "GPT_SoVITS/export_torch_script.py"),
    ("file", "GPT_SoVITS/export_torch_script_v3v4.py"),
    ("file", "GPT_SoVITS/module/models_onnx.py"),
    ("file", "GPT_SoVITS/module/data_utils.py"),
    ("file", "GPT_SoVITS/module/attentions_onnx.py"),
    ("file", "GPT_SoVITS/module/losses.py"),
    ("dir", "GPT_SoVITS/AR/data"),
    ("dir", "GPT_SoVITS/AR/text_processing"),
    ("file", "GPT_SoVITS/AR/utils/initialize.py"),
    ("file", "GPT_SoVITS/AR/models/t2s_model_onnx.py"),
    ("file", "GPT_SoVITS/AR/models/t2s_lightning_module_onnx.py"),
    ("file", "GPT_SoVITS/AR/modules/transformer_onnx.py"),
    ("file", "GPT_SoVITS/AR/modules/activation_onnx.py"),
    ("file", "GPT_SoVITS/AR/modules/patched_mha_with_cache_onnx.py"),
    ("file", "GPT_SoVITS/AR/modules/embedding_onnx.py"),
    ("file", "GPT_SoVITS/BigVGAN/train.py"),
    ("file", "GPT_SoVITS/BigVGAN/discriminators.py"),
    ("file", "GPT_SoVITS/BigVGAN/loss.py"),
    ("file", "GPT_SoVITS/BigVGAN/inference.py"),
    ("file", "GPT_SoVITS/BigVGAN/inference_e2e.py"),
    ("dir", "GPT_SoVITS/BigVGAN/tests"),
    ("file", "GPT_SoVITS/BigVGAN/alias_free_activation/cuda/load.py"),
    ("file", "GPT_SoVITS/eres2net/ERes2Net.py"),
    ("file", "GPT_SoVITS/eres2net/ERes2Net_huge.py"),
    ("file", "GPT_SoVITS/f5_tts/model/backbones/unett.py"),
    ("file", "GPT_SoVITS/f5_tts/model/backbones/mmdit.py"),
    ("file", "GPT_SoVITS/download.py"),
]

T2 = [
    ("file", "webui.py"),
    ("file", "GPT_SoVITS/inference_webui_fast.py"),
    ("file", "GPT_SoVITS/inference_gui.py"),
    ("dir", "tools/uvr5"),
    ("dir", "tools/AP_BWE_main/datasets1"),
    ("file", "tools/slicer2.py"),
    ("file", "tools/slice_audio.py"),
    ("file", "tools/cmd-denoise.py"),
    ("file", "tools/subfix_webui.py"),
    ("file", "tools/my_utils.py"),
    ("file", "tools/i18n/scan_i18n.py"),
]

T3 = [
    ("file", "api.py"),
    ("dir", "tools/asr"),
]


def expand(unit):
    kind, p = unit
    ap = os.path.join(ROOT, p)
    if kind == "file":
        return [(p, UN.get(p, 0))]
    out = []
    for dp, dn, fn in os.walk(ap):
        dn[:] = [x for x in dn if x != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(dp, f), ROOT).replace("\\", "/")
                out.append((rel, UN.get(rel, 0)))
    return out


def report(name, units):
    items = []
    miss = []
    for u in units:
        e = expand(u)
        if not e:
            miss.append(u[1])
        items += e
    # 只统计"确实不可达"的，防止误删可达文件
    safe = [(p, l) for p, l in items if p in UN]
    risky = [(p, l) for p, l in items if p not in UN]
    print(f"\n== {name} ==  删除单元 {len(units)} | 涉及 py {len(items)} | "
          f"确认不可达 {len(safe)} ({sum(l for _, l in safe)} 行)")
    if risky:
        print(f"   ⚠️ 可达文件被纳入，须剔除: {[p for p, _ in risky][:10]}")
    if miss:
        print(f"   [warn] 路径不存在: {miss}")
    return safe


a = report("档1 训练/导出/ONNX变体", T1)
b = report("档2 + GUI与数据预处理", T2)
c = report("档3 + 旧API与ASR", T3)

tot = sum(l for _, l in a + b + c)
print(f"\n三档合计可删 py: {len(a + b + c)} 个 / {tot} 行")
print(f"不可达总量 {len(UN)} 个 / {sum(UN.values())} 行")
print(f"剩余不可达(未纳入方案): {len(UN) - len(a + b + c)} 个")
rest = [p for p in UN if p not in {x for x, _ in a + b + c}]
print("  未纳入:", rest)
