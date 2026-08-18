# -*- coding: utf-8 -*-
"""可选：构建语义检索的稠密向量产物（需本砖 models/weights/bge_small.onnx 就位）。

默认 mock 模式不需要本脚本 —— 引擎直接用 core.HybridRetriever 内存索引。
仅当你想启用「语义升级」（bge 稠密检索）时运行：

    python build_corpus.py

产物落在 data/：
- stitching_corpus.jsonl    ：与内存加载一致的记录（用于运行期一致性校验）
- stitching_vectors.json    ：bge 512 维稠密向量 list
- stitching_meta.json       ：kind=semantic、模型状态

运行要求：onnxruntime + numpy + tokenizers（项目 venv 已含），以及权重文件。
缺权重时脚本会提示并退出，不影响默认 mock 模式。
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from hub import Hub  # noqa: E402
from engine import StitchEngine  # noqa: E402

HERE = os.path.dirname(__file__)
CORPUS_DIR = os.path.join(HERE, "corpus")
DATA_DIR = os.path.join(HERE, "data")


def main():
    hub = Hub()
    if not hub.embedder.available():
        print("未检测到 bge_small.onnx，无法构建稠密向量。")
        print("默认 mock 模式无需本步骤；如需语义升级，请把权重放入 models/weights/ 后重试。")
        return 1
    eng = StitchEngine(corpus_dir=CORPUS_DIR, data_dir=DATA_DIR, hub=hub)
    records = eng.records
    print(f"语料：{len(records)} 条（mock/HybridRetriever 已就绪，现构建 semantic 产物）")

    # 真实编码器无需 idf；稠密向量直接编码 q 字段。
    vectors = hub.embedder.encode([r["q"] for r in records])

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "stitching_corpus.jsonl"), "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(DATA_DIR, "stitching_vectors.json"), "w", encoding="utf-8") as fh:
        json.dump(vectors, fh, ensure_ascii=False)

    meta = {
        "kind": "semantic",
        "dim": hub.embedder._dim,
        "counts": {"total": len(records)},
        "models": hub.status(),
    }
    with open(os.path.join(DATA_DIR, "stitching_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    print(f"构建完成 → {DATA_DIR}（kind=semantic，dim={meta['dim']}）")
    print("模型状态：", hub.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
