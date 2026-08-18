"""声纹砖准确性验证：用 CosyVoice 生成的检验集（3 音色 × 4 句）评估 CAM++ 分离度。

流程（复用砖核心 speaker_core，等价于运行时逻辑）：
1. 逐文件提 192 维嵌入；
2. 每个说话人用第 1 句注册声纹库；
3. 对其余 9 句做 1:N 识别，统计识别准确率；
4. 阈值扫描计算 EER（等错误率），并给出 intra/inter 相似度分布。

用法：`声纹识别/.venv-speaker/Scripts/python.exe 声纹识别/accuracy_test.py`
输出：控制台摘要 + 声纹识别/accuracy_report.md
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

SPEAKER_SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SPEAKER_SRC))

from speaker_core import SpeakerExtractor, SpeakerStore, cosine_similarity  # noqa: E402

TEST_DIR = Path(__file__).resolve().parent / "test_data"
MODEL = SPEAKER_SRC / "speaker_models" / "campplus_zh_en_fp16.onnx"
REPORT = Path(__file__).resolve().parent / "accuracy_report.md"


def discover() -> dict[str, list[tuple[str, str]]]:
    """返回 {说话人: [(wav路径, 文件名)]}，按 spk 前缀分组。"""
    files = sorted(glob.glob(str(TEST_DIR / "spk*_*.wav")))
    groups: dict[str, list[tuple[str, str]]] = {}
    for f in files:
        name = os.path.basename(f)
        spk = name.split("_")[0]
        groups.setdefault(spk, []).append((f, name))
    return groups


def main() -> None:
    groups = discover()
    if not groups:
        print("未找到检验集 wav，请先运行 test_data/gen_test_set.py")
        return
    print(f"检验集：{sum(len(v) for v in groups.values())} 条，"
          f"{len(groups)} 个说话人：{', '.join(sorted(groups))}")

    extractor = SpeakerExtractor(str(MODEL))
    embeddings: dict[str, tuple[str, "object"]] = {}
    for spk, items in groups.items():
        for wav, name in items:
            emb = extractor.compute_from_wav(wav)
            embeddings[name] = (spk, emb)
            print(f"  提嵌 {name} ({spk}) dim={emb.shape[0]}", flush=True)

    # 注册：每个说话人第 1 句
    store = SpeakerStore(str(TEST_DIR / "_speakers_tmp.json"), threshold=0.31)
    for spk in sorted(groups):
        enroll_name = groups[spk][0][1]
        store.enroll(spk, embeddings[enroll_name][1])

    # 1:N 识别（除注册句外）
    correct = 0
    total = 0
    genuine: list[float] = []
    impostor: list[float] = []
    pred_table: list[str] = []
    for name, (spk, emb) in embeddings.items():
        if name in {groups[s][0][1] for s in groups}:
            continue
        res = store.identify(emb)
        pred = res["speaker"]
        sim = res["similarity"]
        total += 1
        ok = (pred == spk)
        correct += int(ok)
        # 分离度评分：与本人注册嵌入（genuine）/ 与其他说话人最高相似（impostor）
        own_sim = cosine_similarity(store.speakers[spk]["embedding"], emb)
        other_sims = [cosine_similarity(store.speakers[o]["embedding"], emb)
                      for o in store.speakers if o != spk]
        genuine.append(own_sim)
        if other_sims:
            impostor.append(max(other_sims))
        pred_table.append(f"| {name} | {spk} | {pred} | {sim:.3f} | {'✓' if ok else '✗'} |\n")

    acc = correct / total if total else 0.0
    print(f"\n识别准确率（阈值 0.31）：{correct}/{total} = {acc:.1%}")

    # 阈值扫描算 EER
    all_scores = sorted(set(genuine + impostor))
    best_eer = 1.0
    best_t = 0.31
    for t in [round(x, 3) for x in [i / 100 for i in range(0, 101, 1)]]:
        frr = sum(1 for g in genuine if g < t) / len(genuine) if genuine else 0
        far = sum(1 for im in impostor if im >= t) / len(impostor) if impostor else 0
        eer = (frr + far) / 2
        if eer < best_eer:
            best_eer, best_t = eer, t
    print(f"EER ≈ {best_eer:.1%} @ 阈值 {best_t:.3f}")

    # 报告
    gmean = sum(genuine) / len(genuine) if genuine else 0
    imean = sum(impostor) / len(impostor) if impostor else 0
    report = f"""# 声纹识别砖准确性验证报告

- 模型：CAM++ fp16 ONNX（campplus_zh_en_fp16.onnx，192 维，中文训练）
- 检验集来源：**CosyVoice 砖零样本克隆生成**（非真实人声，见下方说明）
- 检验集规模：{sum(len(v) for v in groups.values())} 条 / {len(groups)} 说话人（{', '.join(sorted(groups))}），每说话人 4 句不同文案
- 注册：每说话人第 1 句；测试：其余 9 句做 1:N 识别

## 结论

| 指标 | 数值 |
|---|---|
| 1:N 识别准确率 @0.31 | **{acc:.1%}** ({correct}/{total}) |
| EER（等错误率） | **{best_eer:.1%}** @ 阈值 {best_t:.3f} |
| 同说话人相似度均值（genuine） | {gmean:.3f} |
| 跨说话人最高相似度均值（impostor） | {imean:.3f} |
| 分离度（genuine - impostor） | {gmean - imean:.3f} |

## 逐句识别结果

| 文件 | 真实说话人 | 识别结果 | 相似度 | 正确 |
|---|---|---|---|---|
{"".join(pred_table)}

## 说明与局限

1. **检验集是 TTS 合成语音**，非真实人声。CAM++ 在真实语音上训练，对合成语音的
   嵌入空间可能偏移；因此上述准确率/EER 衡量的是「同一克隆音色跨文本的稳定性」与
   「不同克隆音色间的区分度」，作为砖功能可用性的冒烟级验证，**不替代真实人声基准**。
2. 真实人声基准建议用 CN-Celeb / VoxCeleb 子集或实际麦克风录音复测，预期 EER 更低
   （CAM++ 在 CN-Celeb 报告 EER≈4.3%）。
3. 阈值 {best_t:.3f} 由本检验集扫描得到；上线前应以真实人声重新标定 SPEAKER_THRESHOLD。

## 复现

```bash
# 1. 生成检验集（需 CosyVoice 砖 venv）
语音合成 (CosyVoice)/.venv/Scripts/python.exe 声纹识别/test_data/gen_test_set.py
# 2. 跑准确性验证（声纹砖 venv）
声纹识别/.venv-speaker/Scripts/python.exe 声纹识别/accuracy_test.py
```
"""
    REPORT.write_text(report, encoding="utf-8")
    print(f"\n报告已写入：{REPORT}")


if __name__ == "__main__":
    main()
