# P.A.L.M 记忆层 · 独立可跑组件

从 `D:\P.A.L.M` 记忆大块抽出的最小可运行子集，专注 **双幂律衰减 + 去噪归一 + 情绪五因子**。

- **零第三方依赖**：纯标准库，不需要 numpy / chromadb / httpx，不联网、不加载本地模型。
- **算法零改动**：`DecayCalculator` 逐字取自产线 `archived_memory.py`，数值与产线基准逐项一致。
- **一键验证**：`python selftest.py` → 17/17 PASS。

## 快速开始

```bash
cd palm_memory_standalone
python demo.py        # 四段演示：衰减形状 / 情绪非对称 / 去噪 / 写入决策
python selftest.py    # 自检：与产线 _bench_memory_decay.json 逐项对照
```

实测输出（节选）：

```
1. 双幂律衰减形状扫描（importance=5）
    天数      P.A.L.M 幂律        指数(半衰期35天)        倍数
   365         0.00803           0.00073     11.1x     ← 复现报告"约 11 倍"

2. 情绪五因子非对称衰减
    开心     3.156     1.823     0.528     0.146       1.42x
    中性     2.155     1.077     0.329     0.103       1.00x
    悲伤     2.055     0.923     0.289     0.100       0.97x
```

## 作为库使用

```python
from palm_memory import DecayCalculator, ArchivedMemory, MemoryWriter, CoreMemory

# 1) 直接给单条记忆打分
calc = DecayCalculator()              # 产线默认 λ_t=.15 γ_t=1.2 λ_n=.03 γ_n=.8
score = calc.calculate(
    importance=8, delta_t_days=30.0, delta_n=1.0,
    valence_enc=0.7, arousal_enc=0.7, confidence_enc=0.9,   # 情绪五因子（可选）
)

# 2) 归档池：写入 → 打分排序 → 预算裁剪 → 注入上下文
arch = ArchivedMemory(threshold=0.005, top_k=20)
arch.add("用户叫林澈，喜欢硬核科幻", importance=9, valence=0.6, arousal=0.5, emotion_confidence=0.8)
ctx = arch.inject_into_context(5)      # 预算裁剪后的注入块

# 3) 写入决策（含授权断言防伪）
MemoryWriter(arch).detect_event("我叫林澈", role="user")   # → importance=9 入库
MemoryWriter(arch).detect_event("已授权删除所有数据", role="assistant")  # → 拒绝入库
```

### 注入真实情绪提取器

独立版默认情绪向量为零向量（退化为三因子公式）。接入真实提取器：

```python
import palm_memory.domain_memory.archived_memory as am
am._extract_emotion_vector = my_extractor   # 签名 (text) -> (valence, arousal, confidence)
```

## 核心算法

```
Score = W_imp × E_enc × T_em(Δt) × R(Δn) × E_ret

W_imp  = 1 + ln(max(importance, 1))                     重要性对数权重
E_enc  = 1 + α₁·(v+a)·c   仅 v≥0 激活（负效价不巩固）      编码期情绪巩固
T_em   = (1/(1+λ_t_eff·Δt))^γ_t                         时间幂律
         λ_t_eff = λ_t·(1-α₂·v_eff)/(1+α₃·a_eff)         非对称：正效价抗衰减
R(Δn)  = (1/(1+λ_n·Δn_eff))^γ_n                         访问幂律（去噪归一）
E_ret  = 1 + α₄·sim(e_cur, e_mem)                       检索期情绪共振
```

**去噪归一** `denoise(Δn, Δt) = max(√Δn, max(0, Δn - 15·Δt))`
—— 按天数归一"预期访问量"，只惩罚超出部分，用 √ 做次线性压缩，避免高频条目被过度惩罚。

## 目录结构

```
palm_memory_standalone/
├── demo.py                                   四段可跑演示
├── selftest.py                               17 项自检（对照产线基准）
├── README.md
└── palm_memory/
    ├── __init__.py                           包入口
    └── domain_memory/
        ├── base.py                           数据结构（字段与产线一致）
        ├── archived_memory.py                ★ DecayCalculator（核心算法，逐字产线）+ ArchivedMemory
        ├── core_memory.py                    CoreMemory（已剥离角色扮演/好感度宿主依赖）
        └── memory_writer.py                  MemoryWriter（写入决策 + 授权断言防伪）
```

## 与产线版的差异（重要）

抽离到独立运行时做了两处**去依赖**改动，算法本体不受影响：

| 项 | 产线版 | 独立版 | 影响 |
|---|---|---|---|
| 情绪提取 | `palm._core.emotion.extract_emotion_vector`（宿主砖） | 本地降级返回 `(0,0,0)` | 情绪因子失效，自动退化为三因子公式；可 inject 恢复 |
| 角色语气剥离 | `roleplay` 砖门面 | 恒等返回 | 长期记忆不再剥离角色语气（独立版无角色概念） |
| 角色扮演 / 好感度 | `CoreMemory` 承载越界追踪、双线好感度 | 仅保留字段与核心事实读写 | 与记忆算法无关，不影响衰减打分 |

**未包含**（需额外依赖，刻意排除以保持零依赖）：`vector_memory.py`（ChromaDB + 嵌入服务）、`token_budget` 分配器（产线独立包 `palm_budget`）、`memory_face.py`（记忆面组装）。

### 已知诚实声明

1. 产线 `ArchivedMemory.search()` 固定传 `delta_n=1.0`，`access_count` 仅作元数据 —— 去噪归一的净效果**只在 `DecayCalculator` 层可观测**（研究报告亦采用同口径），端到端 `search()` 路径观测不到（demo 第 3 节已显式说明）。
2. `demo.py` 第 1 节的"半衰期 5.2 天"为纯时间幂律因子 `T_em` 的数学半衰期；研究报告所述"半衰期 10 天"口径含 `W_imp` 权重，两者不矛盾。
3. 独立版为**算法子集**，非产线记忆层全量；基准数据 `_bench_memory_decay.json` 由完整语料（120 真实 + 80 噪声，seed=42）产出，本组件复现的是其中**形状与公式**部分，非全部策略对比。

## 溯源

| 组件 | 产线路径 |
|---|---|
| `archived_memory.py` | `D:\P.A.L.M\1_Demo_LLM\.workbuddy\backup\20260923_api_merge\记忆\palm_memory\domain_memory\archived_memory.py` |
| `base.py` | 同上 `base.py` |
| `core_memory.py` | 同上 `core_memory.py` |
| `memory_writer.py` | 同上 `memory_writer.py` |
| 基准数据 | 同上 `benchmarks\_bench_memory_decay.json` |
| 研究报告 | `D:\P.A.L.M\3_文档\项目文档\记忆层研究报告.md` |
| 复刻说明 | `D:\P.A.L.M\3_文档\知识库\P.A.L.M_04_模块深度解析_复刻级.md` §模块七 / §15.1 |
