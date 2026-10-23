# RAG 知识库引擎调研 v1.0

> 2026-09-10｜调研方式：先搜标准流程，再对**每个环节独立深挖**（4 路并行）。
> 目标：为 P.A.L.M 桌面 AI 助手选定离线可用的 RAG 知识库引擎方案。

## 一、标准流程（业界共识）

RAG 流水线分**两个阶段、七个环节**，另有评估作为工程实践的补充环节：

| 阶段 | 环节 | 说明 |
|---|---|---|
| **摄入（离线）** | ① 文档解析 | 多格式 → 带结构与元数据的文本 |
| | ② 分块 | 长文 → 语义连贯的 chunk |
| | ③ 向量嵌入 | chunk → 高维向量 |
| | ④ 向量存储/索引 | 向量 + 元数据落库，建 ANN 索引 |
| **检索（在线）** | ⑤ 检索 | 查询向量 → Top-K 候选（含混合检索） |
| | ⑥ 重排 | 交叉编码器二次排序 |
| | ⑦ 上下文组装与生成 | 拼上下文 → LLM 生成 + 引用溯源 |
| **工程实践** | ⑧ 评估 | 检索侧确定性指标 + 生成侧 LLM 评判 |

参考：腾讯云技术百科、Infercom RAG Workflow、以及多篇企业级 RAG 实践文（见文末来源）。

---

## 二、逐环节结论

### ① 文档解析

**任务**：多格式 → 带结构/元数据的文本或 Markdown。关键决策：格式覆盖、表格与图片、元数据保留、版面还原。

| 库 | 强项 | 弱项 |
|---|---|---|
| **PyMuPDF / fitz**（+ `pymupdf4llm`） | 最快（≈0.05s），直接出 Markdown，表格较好 | 无 OCR |
| **pdfplumber** | 表格最强（`extract_tables`） | 慢、无 OCR；中文需调 x/y tolerance |
| **markitdown**（微软） | 输出标准 MD、LLM 友好 | 表格弱、不处理扫描件 |
| **Docling**（IBM） | 表格与结构化强，离线新秀 | 较新 |
| **unstructured** | 类型最广 + 元素分类 | **重、慢**，部分策略需模型/付费 |
| **python-docx + openpyxl** | Word/Excel 原生零依赖 | 仅 Office 系 |

**选型**：文本 PDF → `pymupdf4llm`；表格 → `pdfplumber` 兜底；Office → `python-docx`/`openpyxl`（XLSX 按"表头 + 行"序列化）；多类型混合 → `Docling`。**避免 `unstructured` 的重依赖**。

**坑**：扫描件需本地 OCR（中文选 **paddleocr** 优于 tesseract）；PDF 双栏乱序用 `sort=True`；表格跨页需手动拼；合并单元格易失败。

### ② 分块

**策略对比**：

| 策略 | 说明 | 取舍 |
|---|---|---|
| 固定长度 | 按字符/token 切 | 简单可预测，**会断语义**，仅作 baseline |
| **递归字符** | `\n\n`→句→词 逐层 | **最常用**，通用性最好 |
| 语义分块 | 句嵌入相似度合并 | 连贯性最佳，但摄入贵、重建慢 |
| **父子/层级** | 子块（128-256 token）检索、父块（512-2000）补上下文 | recall **+10~20%**，存储翻倍 |
| 按结构 | Markdown 标题 / HTML / PDF 区块 | 质量高，映射人类阅读单元 |

**中文要点**：bge-m3 约 **1 字 ≈ 1 token**，**勿用 tiktoken**（英文分词器）；以 `。！？` 作句界优于 `.`；避免半句切断。

**参数建议**：中文 **300-500 字**、overlap **10-15%**（块 >1500 token 时降到 5%）；表格整块不切。

**坑**：固定长度切断句；overlap >20% 或块过大会浪费上下文；OCR/结构丢失会让递归退化；父子块重复未去重；缺页码/标题元数据导致无法溯源。

### ③ 向量嵌入

| 模型 | 维度 | 体积 | 中文 | 备注 |
|---|---|---|---|---|
| **bge-m3** | 1024 | 568M（INT8 ≈220MB） | 66.1 | **自带 dense + sparse + 多语 100+**，ONNX 离线 |
| bge-large-zh-v1.5 | 1024 | 326M | 64.5 | 纯中文，无 sparse |
| multilingual-e5-large-instruct | 1024 | — | 58.8 | 需指令前缀，512 token 上限 |
| text-embedding-3-large | 3072 | API | — | **出网，不符离线要求** |
| jina-v3 | 1024 | — | — | Matryoshka + late chunking，**CC BY-NC 需授权** |
| Qwen3-Embedding | 1024/2560/4096 | 0.6/4/8B | 多语 MTEB 第一 | 4B/8B 需 2.5/4.7GB，桌面 CPU 收益有限 |

**结论：不换 bge-m3** —— 离线、多语、**自带 sparse 可直接支撑混合检索**，中文与体积都达标。ONNX INT8 后 220MB，CPU 单 chunk 约 50-100ms。

### ④ 向量存储与索引

| 方案 | 定位 | 数万级评价 |
|---|---|---|
| **Chroma 1.5.9** | 嵌入式，duckdb 持久化 + HNSW + 过滤 | ✅ **零运维，<百万首选** |
| FAISS | 纯库，HNSW 召回高 | ❌ 无服务/持久化/过滤 |
| Qdrant | Rust 单二进制，过滤最强，标量量化省内存 | 需强过滤时切它 |
| Milvus | 云原生分布式 | ❌ 过重 |
| LanceDB | 列式多模态 | 早期 |
| pgvector | Postgres 扩展，ACID + JOIN | 已有 PG 时最省事 |

**索引算法**：HNSW（M=16/32、`efSearch` 调召回，内存高）；IVF（需训练）；PQ/SQ8 量化省内存 ≈75%、召回略损。数万级 1024 维 HNSW 仅约 **40MB**。

**结论：数万级不必换 chromadb** —— 已跑通、离线零运维，配 bge-m3 的 sparse 即可做混合检索。

### ⑤ 检索

- **必上混合检索**：dense + sparse 均取 bge-m3 ONNX，用 **RRF（k=60）** 融合（免权重校准）。
- **Top-K**：初排取 **40~50**，cosine 度量。
- **查询改写**：默认**不改**（技术语料词表接近用户）；仅对模糊/多跳问题门控启用 Multi-Query（3 路 + RRF）。
- **查询优化手段**：HyDE（+15~25%，专有知识易幻觉）、Multi-Query（+20~35%）、子查询分解（多跳 +30~50%）—— 代价都是额外 LLM 调用。
- **元数据过滤**：低基数类别用 `where` **预过滤**；高基数文本用 `where_document` / 后过滤；过严则**过取 50 再重排**。

### ⑥ 重排

- **为什么**：初排双编码器是近似匹配，易陷"关键词陷阱"；重排用 **Cross-Encoder** 联合注意力打分，精度远超。
- **模型**：**bge-reranker-v2-m3**（568M，基于 BGE-M3-0.5B，中文/多语强，ONNX 可行）为首选；Qwen3-Reranker-0.6B 是自回归解码，**CPU 慢约 3 倍**；jina/Cohere **需联网付费，离线排除**。
- **延迟**：CPU 重排 50 候选约 **3~10s**（INT8 ONNX 更快）；GPU 约 300ms。
- **结论**：离线桌面**必上重排**，链路 **初排 40 → 重排 20~30 → 取 Top 5~8**；CPU 吃紧就降候选到 20 或换 base。

### ⑦ 上下文组装与生成

- **取数**：retrieve 20 → rerank → 取 **top-5**。
- **拼接用 bookend 策略**：最相关段放**首尾**，弱相关填中段 —— 规避 "lost in the middle"（模型重首尾、轻中段）。
- **token 预算**：检索上下文占 **60-70%**，system prompt 约 10-15%，留余量。
- **压缩**：同源重复先去重；超预算用**抽取式压缩**（RECOMP-Extr / LLMLingua）保留原句，再摘要。
- **提示词强约束**：`仅依据 <context> 内引用内容回答，禁止调用自身知识`；每论断标 `[1][2]`；无答案时显式拒答；**temperature 设 0~0.3**。
- **引用溯源**：context 段用标签包裹并附 `source` + 编号；生成后**校验引用真实性**（citation accuracy），杜绝"标 [1] 实则来自 [3]"。

### ⑧ 评估

- **两层指标**：检索侧 Recall@k / Precision@k / MRR / NDCG；生成侧 Faithfulness（拆原子论断逐条验证）/ Answer Relevance / Context Precision。
- **工具**：**RAGAS**（开源、reference-free，可接本地 OpenAI 兼容端点 → **完全离线**）、DeepEval（pytest 集成，可做 CI 质量门）、TruLens（RAG Triad 根因诊断）。LangSmith 需联网商业，仅作追踪补充。
- **无裁判轻量方案**：检索侧用**确定性指标**（基于标注相关 doc 算 Recall@k / MRR），不依赖 LLM；先以 **BM25 baseline** 打底对比。
- **中文评估集**：**30~80 条**即够初版；字段 `question / reference answer / relevant chunk_ids`；用真实文档人工出题 + 标注正确来源，冻结版本便于跨周期对比。

---

## 三、面向 P.A.L.M 的落地建议

**已有资产可直接复用**：

| 环节 | 现状 | 动作 |
|---|---|---|
| ③ 嵌入 | 已用 bge-m3 ONNX（本地） | **不换**；必要时补 INT8 量化 |
| ④ 向量存储 | 已用 chromadb 1.5.9 | **不换**；数万级足够 |
| ⑤ 检索 | 已有 dense 语义检索（阈值 0.72） | 补 **sparse + RRF 融合** |
| ⑦ 生成 | 已有 LLM 调用层 | 补 bookend 拼接 + 引用校验 |

**待补环节**：

| 缺口 | 建议方案 | 依赖 |
|---|---|---|
| ① 文档解析 | `pymupdf4llm`（PDF）+ `python-docx`/`openpyxl`（Office） | 轻量纯 Python |
| ② 分块 | 递归字符分块（中文 300-500 字 / overlap 12%）+ 父子块 | 可自研，~200 行 |
| ⑥ 重排 | **bge-reranker-v2-m3 INT8 ONNX** | 与 bge-m3 同栈 |
| ⑧ 评估 | 自建 30-80 条中文评估集 + RAGAS（离线模式） | 可选 |

**推荐链路**：

```
文档 → pymupdf4llm 解析 → 递归分块（300-500 字/12%）
     → bge-m3 ONNX 嵌入（dense + sparse）→ chromadb
查询 → bge-m3 嵌入 → 混合检索（RRF k=60, Top-50）
     → bge-reranker-v2-m3 重排（取 Top-6）→ bookend 拼装
     → LLM 生成（temperature 0.2 + 强制引用）
```

**取舍说明**：全链路**零出网**，嵌入与重排共用 BGE 系 ONNX 栈，认知与运维成本最低；唯一重资产是 bge-reranker-v2-m3（INT8 后约 220MB），若 CPU 延迟不可接受，可先降候选数或暂缓重排（但精度会明显下降）。

---

## 四、参考来源

- 标准流程：腾讯云技术百科 RAG 工作流程、Infercom RAG Workflow Docs、ima 知识库多篇企业级实践
- 解析/分块：PyMuPDF Docs、onyxlab.ai 数据准备指南、Databricks Community RAG 分块实践、iamdave.ai RAG 数据结构
- 嵌入/存储：HuggingFace `onnx-community/bge-m3-ONNX`、Qwen3-Embedding 官方博客、Jina v3 模型页、vector database 选型对比
- 检索/重排：BAAI bge-m3 / Reranker-v2 官方、RAG 架构实测文、reranker 基准对比
- 生成/评估：Liu et al. 2023 "Lost in the Middle"、RECOMP (2024)、LLMLingua (2023)、RAGAS (2023)、Anthropic Contextual Retrieval 指南
