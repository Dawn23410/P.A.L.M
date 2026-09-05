# palm-metrics skill — 判读层与工具核心算法文档（v0，供 LLM 分析）

> 快照自 `C:\Users\Dawn\.workbuddy\skills\palm-metrics\`，快照时间 2026-09-04 22:xx。**源文件未做任何修改**（工具代码保持现状，不含拆分/重构）。本文件为纯 md 自包含文档，可直接整段喂给任意 LLM 做评审、找问题、评估开源价值。
>
> 源文件指纹（md5）：
> | 文件 | md5 |
> |---|---|
> | scripts/codequal.py | decd80924183b74cb6a88bec591719d5 |
> | scripts/dynprobe.py | b61a69b1de2ea9e01fe39f9ee49a8ddf |
> | scripts/latstat.py | a11d5c8faa24f9f73222caf8e44d91eb |
> | scripts/servemetrics.py | bf8be3a355584587fb8a16bfcfd67aee |
> | scripts/sysmetrics.py | 11079ebf4e8be1cf48640f2f06f68db4 |
> | scripts/mleval.py | c0edc9c2b16a5f683df21636d318de4a |
> | scripts/qoemetrics.py | 2940ca9191a9ec6df5dcf35d99016d6b |
> | scripts/speechmetrics.py | 03bc3774b7329b6f5ea27db1e29566be |
> | SKILL.md | 94b004b1fad3d126292a42b3d0ee2345 |

---

## 目录

1. [架构定位：工具层与分析层分离](#1-架构定位工具层与分析层分离)
2. [全局指标数据契约与口径](#2-全局指标数据契约与口径)
3. [判读层（SKILL.md 分析框架）](#3-判读层skillmd-分析框架)
4. [硬核事实与坑](#4-硬核事实与坑)
5. [工具 1：codequal.py — 代码质量（核心算法最重）](#5-工具-1codequalpy--代码质量核心算法最重)
6. [工具 2：dynprobe.py — 动态测试五族](#6-工具-2dynprobepy--动态测试五族)
7. [工具 3：latstat.py — 延迟/吞吐/可用性](#7-工具-3latstatpy--延迟吞吐可用性)
8. [工具 4：servemetrics.py — LLM/Web/SRE](#8-工具-4servemetricspy--llmwebsre)
9. [工具 5：sysmetrics.py — USE/数据库](#9-工具-5sysmetricspy--use数据库)
10. [工具 6：mleval.py — ML 质量/漂移](#10-工具-6mlevalpy--ml-质量漂移)
11. [工具 7：speechmetrics.py — TTS/STT](#11-工具-7speechmetricspy--ttsstt)
12. [工具 8：qoemetrics.py — 流媒体 QoE](#12-工具-8qoemetricspy--流媒体-qoe)
13. [跨工具已知口径注意点（供 LLM 评审重点）](#13-跨工具已知口径注意点供-llm-评审重点)

---

## 1. 架构定位：工具层与分析层分离

分两层，严格区分职责：

1. **工具层 = 度量衡**：`scripts/*.py` 全部零依赖（Python stdlib only），只产出**规范化、可量化、可复测的指标**（分数/分位/比率/计数，0–100 A–E，JSON 留证）。**不做结论、不绑定用途**——同一份指标数据在任意场景（代码评审、性能验收、安全审计、趋势追踪、AI 代写质量审查……）都能被独立解读。工具演进方向是补"通用指标维度"，不是为某个应用场景做专用开关。
2. **分析层 = 判读方法**：SKILL.md 教 AI **怎么选工具取数 → 对齐口径 → 单指标怎么读 → 组合怎么判 → 出证据链结论**。判读没有按项目类型预设的专属结论表；所有场景走同一套通用方法——差异只在"取哪些轴、各轴权重多少"，这两点由 AI 按场景声明假设、交用户确认，**不改工具**。
3. **触发即用**：用户抛来定性词（"这是不是屎山 / 能不能上线 / 代码烂不烂 / AI 代写质量"）时，不直接下结论——先取指标，再按判读层复述语义拆解 → 映射指标 → 出证据链结论。

**工具总览（scripts/，8 个）**

| 脚本 | 家族 | 选择器 | 输入契约（CSV/JSON 每行一个样本） |
|---|---|---|---|
| codequal.py | 代码质量（核心 6 维加权 + 扩展 3 维） | — | 源码目录/文件路径 |
| latstat.py | 延迟/吞吐/错误/Apdex/SLO/波动（23 项） | — | 延迟样本，或 `--bench 模块::函数` |
| servemetrics.py | LLM 推理 / Web Vitals / SRE 可靠性 | `--kind llm\|web\|sre` | llm: ttft,itl,gen_tokens[,kv_hit,gpu_util,…]；web: lcp_ms,inp_ms,cls,ttfb_ms,fcp_ms,tbt_ms；sre: started,detected,acknowledged,resolved(秒) |
| sysmetrics.py | USE 基础设施 / 数据库 | `--kind use\|db` | use: cpu_util,cpu_runq,mem_util,swap_pct,disk_util,disk_await,disk_queue,net_util,net_drop,net_retrans,…；db: conn_pool_util,replica_lag,lock_waits,deadlocks,cache_hit,slow_query_rate,storage |
| mleval.py | ML 质量 / 漂移 | `--kind quality\|drift` | quality: y_true(+y_pred/y_score)，可加 perplexity/hallucination/groundedness/toxicity；drift: ref,cur 两列或 `--ref/--cur` 两文件 |
| qoemetrics.py | 流媒体/WebRTC QoE | — | fps,rebuffer_ratio,rebuffer_evt_per_min,rtt,packet_loss,jitter,bandwidth,frame_drops,av_sync_offset,startup,cdn_cache_hit,abr_switches,freeze_count,freeze_dur,playback_error_rate |
| speechmetrics.py | TTS / STT | `--kind tts\|stt` | stt: audio_sec,proc_ms,tail_ms,first_partial_ms,wer_pct[,cer_pct,end2end_ms]；tts: audio_sec,char_count,proc_ms,first_audio_ms[,mos,artifact_pct] |
| dynprobe.py | 动态测试：边界/模糊/并发/安全/资源 | `--kind boundary\|fuzz\|concurrency\|security\|resource`（可逗号组合） | target 三形态：`module::func`（白盒）/ `cmd:...`（黑盒）/ `url:...`（HTTP）；security 静态用 `--path`；`--args 'a:int(lo,hi),b:str(2,8)'` 声明参数域 |

通用 CLI 约定：`--demo`（合成样本自检）、`--json <file>`（JSON 留证）、`--fail-under <N>`（综合分低于 N 退出码 1，可做 CI 门禁）。输入 CSV 首列 BOM 内建处理；JSON 顶层数组或 `{"rows":[…]}` 均可。

---

## 2. 全局指标数据契约与口径

- **时间一律毫秒(ms)**，时序样本字段名带 `*_ms`；比率/百分比用 `*_pct` 或 `rate`。
- 顶层结构统一为 `{"tool","version","findings"/"alerts","scores"/"stats","ts"}`（dynprobe 已遵；样本分析类以 `stats` 承载统计量）。**codequal 例外**：顶层为 `{"files","project"}`，`project` 内 `score/grade/parts/summary/raw/raw_thresholds` 承载汇总与判据，`files[]` 逐文件 `metrics` 承载证据。
- **等级口径**：codequal/latstat/dynprobe 用 **A≥90 / B≥75 / C≥60 / D≥45 / E<45**；servemetrics/sysmetrics/mleval/qoemetrics/speechmetrics 内部实际用 **A≥90 / B≥80 / C≥70 / D≥60 / E<60**（两套并存，见 §13 注意点）。
- 文件级明细（codequal top 文件、dynprobe findings）是**证据链**，报告必须带，不能只给总分。
- 各工具 JSON 独立归档可对比；跨版本趋势 = 同工具同参数重跑比对。

**关键阈值口径（默认，均可按场景覆盖）**

| 指标 | 默认门槛 | 对齐说明 |
|---|---|---|
| LLM TTFT p99 | ≤2000ms | 交互档（MLPerf 预算） |
| TPOT p99 | ≤200ms | — |
| SLO | p99 ≤200ms / 99% 样本 | latstat 默认，对齐 P.A.L.M LLM 非网络延迟 <200ms 口径 |
| Web Vitals | LCP≤2500 / INP≤200 / CLS≤0.1 / TTFB≤800 / FCP≤1800 / TBT≤300 (ms) | Google good 档 |
| SRE | SLO 99.9%，MTTR 告警 >1h | 可 `--slo` 调整 |
| USE | CPU/磁盘/网络 util 80% 警 95% 页；mem 85/95；cache_hit≥95 | — |
| DB | conn_pool 80/95；replica_lag 30s；slow_query_rate≤1% | — |
| 漂移 | PSI<0.1 无显著 / 0.1–0.25 中等 / >0.25 显著 | — |
| STT | tail p95≤350ms（Vosk 0.35s）、RTF≤1、WER≤10% | speechmetrics |
| TTS | RTF≤1、首音频字节 p95≤1200ms | speechmetrics |

---

## 3. 判读层（SKILL.md 分析框架）

判读目标：**可复算**——任何人拿同一份 JSON 按本节规则能推出同一判级。判级输出统一：绿(健康)/黄(局部问题)/红(问题重) + 证据列表 + 一句结论。

### 3.1 判读总原则

1. **单指标不定罪**：结论必须 ≥2 个独立信号共振 + 文件/样本级证据；单个维度低分只说明"该属性有问题"，不直接等于"整体烂"。
2. **等级只信 JSON**：以工具输出 `score`/`grade` 字段为准，不凭印象心算重估。
3. **先看分、再看级、后取证据**：每个维度先按 0–100 分定位健康度 → 下钻 JSON 明细（`raw`/`summary`/逐文件 `metrics`）→ 定位"红在哪个文件/样本区间"→ 才写结论。
4. **方向对齐**：所有维度分都是"越高越健康"（扣分制）。结论直接说属性问题（"复杂度超标、集中在 A.py 的 fn_x"），不要绕成分数。
5. **覆盖度声明**：某属性当前没有指标可测时，**必须显式声明该信号缺失**，不得用相邻指标冒充。

### 3.2 单指标读法（四大信号族）

**族 A · 0–100 加权维度分**（codequal `project.parts`/`files[].result.parts`、各脚本总 `score`）
- 档位读法：≥90(A) 健康；75–89(B) 良好可看明细；60–74(C) 局部问题须下钻；45–59(D) 明显失控必须点名证据；<45(E) 重灾。**D/E 档是红灯信号源，B 以上是绿灯信号源，C 是黄灯（先定位再定性）**。

codequal 九维语义与证据位置：

| parts 键 | 度量什么 | 证据在哪（下钻定位用） |
|---|---|---|
| complexity | 圈/认知复杂度、嵌套深度 | `summary.over_cc`/`over_cognitive`；逐文件 `metrics.max_cc`/`max_cognitive`/`max_nesting`；`raw.complexity` |
| unit_size | 函数行长、参数数、文件体积 | `summary.over_loc`/`over_params`；逐文件 `metrics.loc`；阈值 `func_loc`/`func_params`/`file_loc` |
| duplication | 重复代码占比（默认阈值 2.0%） | `summary.duplication_pct`；逐文件 `metrics.dup_lines` |
| coupling | 模块依赖扇出 | `raw.coupling`（平均扇出）；逐文件 `metrics.fanout`；阈值 `fanout`(15) |
| readability | 注释密度(8–35%)、命名质量、超长行 | 逐文件 `metrics.vague_names`、`long_lines`、注释占比 |
| efficiency | 循环内 IO/资源调用等静态坏味道 | `summary.efficiency_hits`；逐文件 `metrics.efficiency_hits` |
| dead_code | 未使用 import + 模块级私有 `_x` 零引用 | `summary.unused_imports`/`dead_private_total`；逐文件 `metrics.unused_imports`/`dead_private`（`[行,名]` 清单） |
| naming | 四主流风格皆非的混搭名 | `summary.naming_violations`；逐文件 `metrics.naming_violations`（`[行,名,类别,期望风格]`） |
| clones | 跨文件近重复块（结构骨架 Dice ≥ `clone_sim`） | `summary.clone_groups`/`clone_funcs`/`clone_edges`；逐文件 `metrics.clone_partners`/`clone_hits` |

- 合成口径：总分默认 **core** 口径只算 6 核心维（权 25/20/15/10/15/15，和 100）；`--dims all` 纳入扩展 3 维（dead_code 10 / naming 5 / clones 10，和 125 重新归一）。JSON `summary.dims` 记录口径——**跨 JSON 比总分前先核对二者一致**。

**族 B · 分位/分布统计**（latstat 等 `stats`）
- p50 看典型体验，p99/p999 看尾部；**尾距比 p999/p50**：>10× 提示抖动，>30× 存在明显异常样本。
- 达标与否以工具输出判据字段（Apdex/SLO 合规率）为准；**n<1000 时 p99.9 声明仅供参考**。
- 亚毫秒样本高阶矩自动置 0，此时只看 QPS/CoV。

**族 C · 计数/命中类告警**（dynprobe findings、security HIGH/MED/LOW）
- 命中 = "可疑面"，不是"已定罪"。测试/样例/文档语境降权；生产路径 HIGH 必须逐条看。
- 证据必须带定位（文件:行 / 最小复现输入 / 样本区间）。

**族 D · 状态/比率类**（sysmetrics USE、mleval PSI、speechmetrics WER）
- 读法 = 对照阈值表的黄/红带；漂移/分箱类结论须满足最小样本量。

### 3.3 组合判读（多信号合议）

1. **同族共振才升级**：complexity D/E × unit_size D/E → "大而乱的函数"；duplication C × unit_size 低 → 复制粘贴堆叠；readability C × complexity C → 维护成本最高；coupling 高 × complexity 低 → 先做函数内拆分。
2. **跨族是独立轴，不互相抵消**：静态结构 ≠ 运行时性能 ≠ 安全面。"结构 A + 安全 HIGH≥3" ≠ 健康；"性能达标" ≠ 结构可维护。
3. **合议定级法（可复算）**：每轴落单轴等级——绿=无 D/E 档且无未排除高危；黄=存在 C 档或待复核证据；红=存在 D/E 档或高危命中——**全绿 → 绿；任一轴红 → 红；其余 → 黄**。结论必须写明"是哪一轴把整体拖黄/拖红"。
4. **加权假设要声明**：AI 说明权重取舍，用户可纠正；纠正只改解释，不改已取数据。

### 3.4 定性词 → 指标映射（语义触发，无预设子域）

用户抛"这代码行不行 / 烂不烂 / 是不是屎山 / AI 代写质量 / 能不能上线"等定性词时，走五步流程：

1. **语义拆解**：AI 一句话复述该词在此语境 = 哪些可量化属性，列假设清单，先说出口等用户确认。示例拆法："屎山" = 结构混乱（复杂度/嵌套）+ 堆叠臃肿（单元规模/重复）+ 牵一发动全身（耦合/依赖面）+ 无人能读（可读性/命名）+ 暗藏风险（安全面）。
2. **属性 → 指标映射**：结构/堆叠/耦合 → codequal；暗藏风险 → dynprobe security **独立轴**；跑不跑得动 → latstat/servemetrics。
3. **覆盖度检查**：已覆盖：语义重复 → clones、死代码 → dead_code、命名 → naming、安全数据流部分覆盖（dynprobe 函数内轻量污点标注）。**当前仍无指标**：跨函数/跨模块污点分析、依赖/供应链漏洞（无 CVE 库比对）、测试覆盖率（不接 coverage）。落到未覆盖区，明说"该信号当前无指标，结论降级为保守"，不得用模式命中冒充污点分析。
4. **判读**：套族读法 + 合议 + 结论模板。
5. **闭环**：用户异议 → 回第 1 步只改假设与权重；已取数中立，不推翻。

### 3.5 结论模板（证据链缺一不可）

`判级（绿/黄/红） + 各轴等级一句话 + 证据列表（文件/样本区间+关键数字） + 拖累判级的具体原因 + 一句可执行建议`。例：
> 整体**黄**。轴1 结构=黄：codequal B/85.2 但 duplication 是唯一 C 档轴（64.9，重复率 15.2%≈阈值 7.6 倍，dup_lines 集中在 3 个大文件）；轴2 安全=绿：dynprobe security 排除测试/样例语境后 HIGH=0；轴3 运行时未测，不参与定级。拖黄主因=重复率维度 C。建议先消重。

---

## 4. 硬核事实与坑

1. **百分位不可跨时间窗平均**（tp99 必须按原始样本/HDR 重算）——latstat 已内建；多窗口想合并就合原始样本再跑一次。
2. **压测防 coordinated omission**（wrk2/vegeta 常量速率才准）——benchmark 结论别用丢尾的 load generator 数字背书。
3. **偏度/峰度在亚毫秒样本会数值爆炸**——latstat 已内建噪声底（std/mean<1e-3ms 置 0），此时看 QPS/CoV 而非高阶矩。
4. **PSI/JS 等分箱指标在 n<~100 时不稳定**——漂移结论至少几百样本；bin 按参考分位数等频切。
5. codequal 是**静态源码测量**，与运行时工具互补，不是替代。
6. dynprobe 白盒执行在**子进程隔离**跑（每用例一个 `python -c` 子进程，防真崩/OOM/死锁拖死宿主）；大输入走 stdin 规避命令行长度限制；Windows 下路径用 `C:/...` 风格。
7. dynprobe security 是**模式匹配级 + 函数内轻量污点标注**：命中注入/反序列化（[A03]/[A08]）时若实参可溯源到外部输入，JSON 该 finding 追加 `tainted: true` 与 `flow` 步骤链。不做跨函数/跨文件跟踪；**命中≠可利用**——污点标注只是"外部可达、优先人工复核"提示，未标污点的非字面量命中仍需人工判读；硬编码密钥/`os.system` 拼接高置信；`random`/`md5` 类已按低误报收紧。
8. 各脚本评分是**内部一致的相对门禁**，用于趋势/门槛判断；跨脚本不横向比绝对值。
9. codequal 总分由权重合成，**单维度 C/D 会被高分维度均摊**——判读必须逐维看 `project.parts` 与明细，总分只用于横向门槛与趋势；比总分前先核对 `summary.dims`。

---

## 5. 工具 1：codequal.py — 代码质量（核心算法最重）

**输入**：源码文件或目录（23 种扩展名映射 21 种语言）。自动跳过 SKIP_DIRS（.git/node_modules/__pycache__/.venv/venv/dist/build/vendor/site-packages 等 26 个）与 SKIP_PATH_RE（runtime stdlib 副本、site-packages、dist-packages、node_modules、third_party）；`--exclude` 追加正则。

### 5.1 阈值档 PROFILES（全部可调，集中一处）

| 参数 | default | strict | loose |
|---|---|---|---|
| func_loc 函数行长上限 | 50 | 30 | 80 |
| func_cc 圈复杂度上限 | 10 | 6 | 15 |
| func_cognitive 认知复杂度上限 | 15 | 10 | 25 |
| func_params 参数上限 | 4 | 3 | 6 |
| max_nesting 嵌套上限 | 3 | 2 | 4 |
| file_loc 文件行上限 | 500 | 300 | 800 |
| duplication_pct 重复率阈值 % | 2.0 | 1.0 | 5.0 |
| comment_min/comment_max 注释占比 | 0.08/0.35 | 0.10/0.30 | 0.05/0.40 |
| line_width 行宽 | 120 | 100 | 150 |
| fanout 扇出上限 | 15 | 10 | 25 |
| clone_min_lines / clone_min_tokens / clone_sim | 6 / 8 / 0.80 | 5 / 6 / 0.75 | 8 / 10 / 0.85 |

### 5.2 权重与分档

- **WEIGHTS（core 6 维，和 100）**：complexity 25、unit_size 20、duplication 15、coupling 10、readability 15、efficiency 15。
- **EXTRA_WEIGHTS（扩展 3 维，`--dims all` 时并入）**：dead_code 10、naming 5、clones 10（和 125 重新归一）。
- **GRADES**：(90,A,★★★★★) / (75,B,★★★★) / (60,C,★★★) / (45,D,★★) / (0,E,★)。
- 维度标签：complexity 复杂度 / unit_size 单元规模 / duplication 重复率 / coupling 耦合度 / readability 可读性 / efficiency 效率风险 / dead_code 死代码 / naming 命名一致性 / clones 近似克隆。

### 5.3 单文件原始度量（AST，Python）

- **行统计**：code/comment/blank 分离（python/shell 用 `#`；其余 `//`、`/* */`、块注释状态机）。
- **函数圈复杂度 CC**：`score=1`；`ast.walk` 遇 if/for/while/except/with/assert/IfExp/comprehension 等决策节点 +1；BoolOp 短路分支 `+len(values)-1`；match 语句 `+len(cases)`。
- **认知复杂度**：SonarSource 式 `+1+nesting` 于 if/loop/except；**两处刻意豁免**——else-if（elif 是 AST 嵌套 If，读起来平铺，不加深嵌套）、switch/match 整块只记 1。表达式层：IfExp `+1+nesting`、BoolOp 序列记 1、推导式 `+len(generators)`。嵌套 FunctionDef/ClassDef 单独计量不并入外层。
- **函数 LOC**：`end_lineno - lineno + 1`。**参数数**：posonly+args+kwonly+(*a 或 **kw 各 +1)。
- **Halstead 体积**：tokenize 后 V = N·log₂(n)（N 总 token、n 不同 operator+operand）。
- **可维护性指数 MI**（微软变体）：`raw = 171 − 5.2·ln(V) − 0.23·avgCC − 16.2·ln(LOC)`；`MI = clamp(raw·100/171)`。≥85 高可维护，65–85 中，<65 低。
- **扇出 fanout**：import 目标去重计数（import a.b → a；`from x import y` 取 x；相对 import 记为 `<relative>`）。

### 5.4 文件级九维评分（全部扣分制，越高越健康，clamp 0–100）

设 n=函数数、th=阈值档。所有维度先算好再经 `score_file` 合成。

1. **complexity**：无函数 → `100 − max(0, loc−file_loc)·0.05`；否则
   `pen = (over_cc/n)·45 + (over_cognitive/n)·35 + max(0, max_nesting−th)·5 + (over_params/n)·15`，`score=100−pen`。
2. **unit_size**：无函数 → 100；否则 `pen = (over_loc/n)·60 + min(40, Σ(loc−th)/n·2)`；文件行超 `file_loc` 再 −5。
3. **duplication**：文件级 `rate` = 该文件自身 `dup_lines / code_lines · 100`（`dup_lines` 来自全局 5 行窗扫描的命中行号集合，见 §5.6）；`rate≤threshold → 100`；否则 `100 − (rate−threshold)·8`。
4. **coupling**：`fanout≤threshold → 100`；否则 `100 − (fanout−threshold)·4`。
5. **readability**：注释占比 r=comment/(code+…)：r<min → `+(min−r)·120`；r>max → `+(r−max)·60`；超长行 `+min(20, long_lines/total·100)`；模糊命名 `+min(15, len(vague)·1.5)`；MI<65 → `+(65−MI)·0.3`。
6. **efficiency**：`100 − io_in_loop×12 − str_concat_in_loop×4`。
7. **dead_code**：`100 − 未用import×7 − 私有死代码×9`。
8. **naming**：参与判定标识符 <8 个的文件直接 100（小文件中性防噪）；否则 `100 − min(40, 违规数×5)`。
9. **clones**：无函数或无命中 → 100；否则 `100 − 60·(clone_hits/n) − min(20, partners×2)`。

### 5.5 项目级聚合（aggregate）

- **数据/资源型文件剔除**：`loc≥800 且函数数≤2`（i18n 字典、枚举表、fixture）→ 不进评分，记入 `summary.excluded_data_like`。
- **文件级总分**：`score_file` 内 `Σ parts[k]·WEIGHTS[k] / 100`（**默认只用 6 核心维**；parts 恒输出 9 维供判读层随时读，但不并入 legacy 总分）。
- **项目级 parts**：按**代码行数加权平均**（Σ parts·code_lines / Σ code_lines），不是按文件数或函数数平均。注意：`parts.duplication` 因此是**文件级 duplication 分的行加权平均**，并非把全局 5 行窗重复率直接代入 `score_duplication`；全局重复率本体展示在 `raw.duplication`（百分比+阈值对照），两者读数口径不同、勿混淆。
- **项目总分**：`Σ parts[k]·w[k] / Σw`（core → /100；all → /125）。
- **输出 JSON 结构**：顶层 `{project:{score,grade,stars,parts,raw,raw_thresholds,summary}, files:[{metrics,result}]}`；`summary` 含 files/code_lines/langs/func_count/over_*/duplication_pct/efficiency_hits/avg_mi/unused_imports/dead_private_total/naming_violations/clone_*/excluded_* 与 **profile/dims 口径字段**。

### 5.6 跨文件算法

**重复率 duplication（行级）**：
1. 每行归一化 `norm_line`：去注释行（#、//、*、/* 开头），压缩空白，`len≤12` 的行丢弃；
2. 全语料 5 行滑动窗口，窗口内容 hash 作为 key，首次出现记 (file,idx)，再次出现 → 两个文件的 5 个行号都入重复集合；
3. **重复率 = 重复行号集合大小 / 归一化总行数**（行号集合去重：同一行被 N 个副本命中只算一次，防分子膨胀超 100%）。

**近似克隆 clones（语义级，与行级互补）**：
1. 只扫 Python；函数体行数 ≥ clone_min_lines；
2. 结构骨架 token：tokenize 后**只保留运算符(OP)与关键字(NAME in kwlist)**，剥离全部标识符/字面量/常量 → "复制后改变量名/字面量"的副本会撞出相同骨架；
3. 骨架 token 数 ≥ clone_min_tokens；
4. **前 4 个骨架 token 分桶**（桶内两两比较，桶 >300 跳过防噪声）；
5. 相似度 = Dice 系数 `2·|A∩B| / (|A|+|B|)`（骨架二元组集合）；≥ clone_sim → 成边；
6. 并查集聚合连通分量 → clone_groups；involved 函数数 → clone_funcs；每文件记录 partner（`文件名:行 (函数名, dice 0.xx)`，最多 12 条）。

**死代码 dead_code（只做高置信项，误报控制优先）**：
- 未用 import：仅模块顶层；`__init__.py` 整体跳过（重导出惯例）；**`from __future__ import` 直接跳过**（annotations 等非真实绑定）；`import *` 跳过；TYPE_CHECKING 块不在顶层天然豁免。
- 使用判定 = 全文件 Name Load 计数 + **字符串字面量内标识符词集**（抓 `__all__` 重导出、字符串注解等真实用法，宁可漏报不可误报）。
- 私有死代码：模块顶层 `_x` 定义（非 dunder）全文件除自身定义体外 Load 引用 ≤0。
- **不做**公开符号的跨文件可达性分析（框架自动发现/名字字符串注册会制造狼来了）。

**命名一致性 naming**（四种主流风格，剥离前导下划线判定）：
- 正则：`_RE_SNAKE ^[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?:_[A-Z])?_?$`；`_RE_CAMEL ^[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$`（首字小写后含大写）；`_RE_PASCAL ^[A-Z][a-zA-Z0-9]*$`；`_RE_UPPER ^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$`。
- **只记"四主流风格皆非"的混搭怪名**；纯 snake/camel 混布只计数不上报（一致性信息交判读层）。
- 豁免：dunder；函数 def 名 PascalCase → 记违规，**但全大写放行**（`def X()/Y()` 坐标闭包）；类须 Pascal/UPPER；参数名（len>2、非 other、非全大写）；Store 绑定任意主流风格即放行（UPPER=常量任意作用域如 PAD_L 解包/类常量 STRICT；Pascal=类/类型别名如 `CryptSM4 = ...`）。
- 额外统计 fn_snake/fn_camel/fn_other 项目级分布，输出于 raw.naming。

**效率风险 scan_efficiency**：基于行缩进状态机识别循环体，循环内命中：
- `IO_PATTERN`：open/requests.get/post/urlopen/subprocess.*/cursor.execute/session.query/.commit()/read_csv/to_sql/time.sleep/os.system/shutil.copy|move/.write(/.read( → io-in-loop；
- `QUERY_PATTERN`：.execute/executemany/query/save/insert/update/delete/upsert/bulk_create/find_one/find_all/filter_by/fetchall/fetchone → io-in-loop；
- `CONCAT_PATTERN`：`x += <含字符串字面量/格式化/%/.format>` 才算 str-concat（防 n+=1 误报——实测最高频误报源）。刻意不含 `.get(/.find(`（Google Tricorder 经验：误报率>10% 宁漏勿狼）。

**非 Python 语言**：正则估算（LOOP_RE 按语言、CC 决策关键字计数+1、嵌套按缩进宽度、fanout 按 import/using/#include 正则）；Halstead 仅 js/ts 计算。精度标注"趋势参考"。可选 `--engine lizard` 升级（20+ 语言，未安装自动降级）。

**CLI**：`codequal.py <path> [--profile default|strict|loose] [--dims core|all] [--top N] [--json f] [--engine builtin|lizard] [--fail-under N] [--exclude 正则(可重复)]`。退出码：0 通过 / 1 低于 fail-under / 2 路径或语言错误。

---

## 6. 工具 2：dynprobe.py — 动态测试五族

**定位**：通用动态测试工具（boundary/fuzz/concurrency/security/resource）。0–100 分 + A/B/C/D/E；GRADE=(90,75,60,45)；严重度扣分 SEC_SUS = high 25 / medium 10 / low 3。单用例子进程超时 2s。

**被测对象三形态**：
- `module::func` 白盒：module 可为可导入模块名或 .py 文件路径；func 支持 `Class.method` 链；
- `cmd:<command>` 黑盒：subprocess 执行，参数映射 argv/stdin；
- `url:<http://...>` 端点：urllib 探测。
- `path:`（内部形态，供 `--kind security --path`）。

**--args 参数规格 DSL**（优先于函数注解推断）：`"a:int,b:float,c:str(1,20),d:bool,e:list,f:any"`；int/float 范围 `(min,max)` 闭区间；str 同法表长度域。整体正则扫描避免范围里逗号干扰。

**子进程执行协议**：每用例一个 `python -c <CHILD_CODE> <payload>`；payload=base64(JSON)；≤4KB 走 argv，否则走 stdin（规避 Windows 命令行长度限制）。`sys.set_int_max_str_digits(0)` 允许巨整数。结果经 `DYNPROBE_RESULT <json>` 协议线返回。**结果分类（kind）**：
- `pass` 正常返回；`reject` 合理拒绝（ValueError/TypeError/KeyError 及其 MRO 子类 + YAMLError/ScannerError/ReaderError/XMLSyntaxError/HTMLParseError 解析类——不是缺陷）；`suspicious` 其它裸异常（疑似缺陷）；`crash` SystemExit 或无协议输出的非零退出（解释器级崩溃）；`oom` MemoryError；`hang` 子进程超时。
- 无协议输出且 exit=0 → suspicious。

**参数用例生成**：
- 数值：EP 代表 + BVA 三值（lo−1/lo/lo+1、hi−1/hi/hi+1）+ 特殊值（int: 0/−1/1/±MAXINT/±10¹⁸/2⁶³−1；float: 0.0/−0.0/1e−300/1e300/1e308/±Inf/NaN）+ 类型错乱（字符串"1"/"abc"、1.5、bool）。
- 字符串：空串/纯空白/1字符/下界±1/上界±1/超长10×（无界时 64/1000/100k）/控制字符/shell 注入字符/中文+emoji+零宽/换行制表/孤立代理项。
- list：空/单/5元素/含 None/混合类型/嵌套 4 层/空内嵌/字典。bool：True/False/1/0/"true"。any：None/任意对象/字典。
- 单参数变异法：每次只变异一个参数（其余取代表值 rep）。

### 6.1 boundary（边界/等价类）

- 对每参数每用例调用，观察 kind。**关键发现类型**：声明了范围却静默接受越界值 → `warn`（可能缺校验）；suspicious → medium；hang/crash/oom → high。
- **评分**：`100 − sus×25 − hang×15 − oom×30 − silent×5`。

### 6.2 fuzz（随机 + 不变量 + 最小化复现）

- 自带 LCG RNG（`seed`，确定性可复现）；size=1+(iter%6) 轮转；str 长度 ≤ min(200, 4·size²+20)，字符池含空白/控制/shell/中文/emoji。
- 失败样本只记前 5；**shrink 最小化**：对前 3 个失败样本，用二分找保持"崩溃不变量"的最小形态——字符串截前缀、整数缩绝对值。
- **评分**：`100 − fails×20 − hang×10`。

### 6.3 concurrency（台阶加压 + 饱和点 + 一致性自检）

- 并发台阶 1/2/4/8/16/32（可加 `--max-conc`）；每级开 n 线程 × calls_per_thread 调用的子进程（线程在子进程内跑，宿主不受威胁）；每级超时 `max(30, timeout·lv)` → 判定死锁并中断。
- 记录每级 QPS；**饱和点 = 首次 QPS 环比 <5%** 的并发级。
- **评分**：`100 − errors×10 − 30(死锁) − 15(饱和点过早，conc<2)`。url 形态用线程发 HTTP（每级按最慢响应计 dur），评分 `100 − errors×10`；cmd 形态并发拉起进程。

### 6.4 security（静态 AST 扫描 + url 动态探测 + 污点标注）

**扫描范围**：`--path <目录/文件>`（或从函数 target 回退到模块文件）。内建跳过 node_modules/.git/__pycache__/.venv（.venv/site-packages/venv 仅在 --path 不在 site-packages 内时剔除）；`--exclude` 追加完整路径正则（如 `'GPT-SoVITS|_legacy_tools'`）。

**AST 规则表（扫描 Call 节点）**：

| severity | 规则 | 标签 |
|---|---|---|
| high | eval/exec/__import__(非常量实参) | 代码注入 [A03] |
| high | os.system/os.popen/commands.getoutput（非常量实参） | 命令注入 [A03] |
| high | subprocess run/call/check_*(shell=True 字面量且非常量实参) | 命令注入 [A03] |
| medium | Popen 字符串表达式拼接命令（非 list 参数） | 建议 list [A03] |
| high | pickle.loads / shelve.load / pickle.load / yaml.unsafe_load / yaml.load 未显式 SafeLoader | 不安全反序列化 [A08] |
| medium | marshal.loads(非常量) | 反序列化 [A08] |
| low | hashlib.md5/sha1 | 弱哈希 [A02] |
| medium | requests/urllib/httpx verify=False | TLS 降级 [A07] |
| medium | Flask/FastAPI debug=True 字面量 | 调试后门 [A05] |
| high/medium | cursor/conn/session/db 上 execute/executemany：JoinedStr 内插复杂表达式(high)/仅 Name(medium)；`%` 拼接(high) | SQL 注入 [A03] |
| low→high | 硬编码密钥（见下） | 密钥泄露 [A07] |

**硬编码密钥判定**：赋值目标/关键字名/字典键匹配 `(password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|auth[_-]?key|session[_-]?secret)`；值须为字符串常量；**placeholder 排除**（your_/example/changeme/xxx/TODO/test/demo/… 前缀、2–8 字纯中文、长度<6）；字典键以 uri/url/endpoint 结尾的排除；`/tests/`、test_ 前缀、selftest、bench 语境降级 low，否则 high。输出掩码显示前 4 字符。

**函数内轻量污点标注（tainted/flow，加性——只给既有 [A03]/[A08] 命中补标注，绝不新增/删除命中，基线零回归）**：
- **污点源**：函数参数（含 *args/**kwargs，作为"调用方数据可达"种子）、os.environ.get/pop/getenv、sys.argv[i]、input()、open() 读取（read/readlines/readline/read_text/text/content/json）、网络响应（requests/httpx/urllib 根调用）。
- **传播**：同一作用域内按语句顺序——赋值直传（=、注解赋值、AugAssign 并集）、拼接（BinOp/JoinedStr/f-string）、属性链/方法调用、下标（`sys.argv[0]`/`os.environ[k]` 即来源）、容器（tuple/list/set/dict）、IfExp/UnaryOp；**分支（if/while/for/try/with）乐观取并集**（只虚标不新增命中，宁多标不漏）。
- **sink 家族**（与 scan_file 规则对齐）：eval/exec/__import__、os.system/os.popen/commands.getoutput、subprocess Popen/run/call/check_*(shell=True 或 Popen 非 list)、pickle/marshal loads、shelve/pickle load、yaml.load/unsafe_load、SQL execute/executemany 拼接。
- **产出**：high/medium 且 detail 尾部 [A03]/[A08] 的 finding，若该行有污点流 → 追加 `tainted: true`、`flow: [步骤链]`、detail 尾注"（污点：外部输入可达）"；终端行尾显示 `↳ 污点链: …`。
- **不做**跨函数/跨文件跟踪（噪声控制）；命中≠可利用，未标污点的非字面量命中仍需人工判读。

**url 动态探测**：GET 端点，检查 4 必检安全头缺失（HSTS/CSP/X-Frame-Options/X-Content-Type-Options → low）、Server 指纹暴露（nginx/apache/iis → low）、错误页堆栈泄露（Traceback/".py", line/Exception Type → medium）；端点不可达 → score 0。

**评分（security）**：`100 − Σ SEC_SUS(severity)`。

**JSON 输出**：`{tool:"dynprobe", version, target, kind[], args, scores:{kind:score}, findings[], ts}`。demo 内置 6 个缺陷靶函数（无锁计数器/parse_range IndexError/explode/slurp 深递归等）。

---

## 7. 工具 3：latstat.py — 延迟/吞吐/可用性

**输入**：CSV/纯文本每行 `延迟ms[,状态[,时间戳秒]]`（状态 1/ok/true/2xx=成功，0/fail/error/5xx=失败，数字按 2xx 判）；JSON 数字数组 / dict 列表（latency_ms|latency|dur_ms + ok|success + ts|timestamp）/ `{"samples":[...]}`。

**默认值**：SLO=200ms（对齐 P.A.L.M "LLM 非网络延迟 <200ms"）、slo_pct=99、Apdex T=200ms（4T=800ms 容忍上限）。GRADES=90/75/60/45。

### 7.1 统计（23 项）

- 分位数：**线性插值，与 numpy 默认一致**（rank=(n−1)p/100），一律从原始样本重算。输出 p25/p50/p75/p90/p95/p99/p999。
- 吞吐：有 ts → n/(max−min span)；bench → 采样数/墙钟。
- 错误率 %、**Apdex = (Satisfied + Tolerating/2)/Total**（≤T 满意、≤4T 容忍、>4T 或失败 = frustrated）。
- SLO 合规率 = ≤slo_ms 样本占比；`slo_meets` = 选定百分位值 ≤ slo_ms。
- **tail_ratio = p999/p99**（队列积压代理信号）。
- **波动/分布形态**：IQR=p75−p25；MAD=median(|x−median|)；CoV=std/mean·100%；偏度/超额峰度 Fisher 总体矩（m3/sd³、(m4/sd⁴)−3）；**噪声底：sd<1e-3 或 mean<1e-3（亚毫秒分辨率地板）→ skew/kurt 置 0**（此时看 QPS/CoV）；jitter=相邻样本差绝对值均值（call-to-call 抖动）；p95/p50、p999/p50。
- 小样本提示：n<1000 → `low_sample_warn`（p99.9 噪声显著）。

### 7.2 综合评分（四项减分，封顶各自上限）

1. SLO 超标（选定百分位 pval>slo）：`min(50, (pval/slo − 1)·100)`；
2. 错误率：`min(30, error_rate·10)`；
3. Apdex<0.94：`min(25, (0.94−apdex)·100)`；
4. 尾延迟放大 p999/p99>5：`min(20, (ratio−5)·3)`。
→ clamp 0–100 → grade。

### 7.3 benchmark 模式

`--bench 模块.py::函数`（或可导入模块）：warmup 默认 100（异常吞掉）→ iterations 默认 1000 → `time.perf_counter()` 逐次计时（异常记为失败不退出）→ 返回样本 + 墙钟（推 QPS）。**只测真实完成耗时，规避 closed-loop coordinated omission**。

**JSON 结构**：`{source, score, grade, stars, advice[], stats:{count/ok/fail, min_ms..std_ms, percentiles_ms{}, throughput_rps, error_rate_pct, apdex, apdex_T_ms, slo_ms/slo_pct/slo_compliance_pct/slo_meets, tail_ratio_p999_p99, low_sample_warn, variability:{iqr_ms, mad_ms, cov_pct, skewness, excess_kurtosis, jitter_ms, p95_p50_ratio, p999_p50_ratio}}}`。退出码 0/1(fail-under)/2(错误)。

---

## 8. 工具 4：servemetrics.py — LLM/Web/SRE

注意：本工具 grade 用 90/80/70/60 五档（非 75/45 档）。

### 8.1 LLM 推理（--kind llm）

字段：ttft(ms)、itl/tpot(ms 逐 token 间隔)、gen_tokens/total_tokens、span_s(可选)、gpu、kv_hit(0-1)、gpu_util(0-100)、kv_usage(0-100)。

- TTFT p50/p95/p99；TPOT mean/p99；TPS（有 span → Σtokens/Σspan_s；否则 Σgen/(Σitl/1000)）；per-user TPS = gen_tokens/((ttft+itl)/1000) 平均；TTLT mean ≈ ttft_p50 + tpot_mean·(mean gen/1000)；每 GPU token/s = TPS/gpu 数；KV 命中率/GPU 利用/KV 占用均值。
- **评分**（pen 封顶 35/25/15/10）：
  - TTFT p99>2000 → `min(35, (p99/2000−1)·25)`；
  - TPOT p99>200 → `min(25, (p99/200−1)·20)`；
  - kv_hit<90 → `min(15, (90−rate)·0.5)`；
  - gpu_util<40 → `min(10, (40−util)·0.25)`。

### 8.2 Web Vitals（--kind web）

阈值表 (good, needs-improvement)：LCP(2500,4000)、INP(200,500)、CLS(0.1,0.25)、TTFB(800,1800)、FCP(1800,3000)、TBT(300,600)，单位 ms（CLS 无量纲）。

- 输出各指标 p75 + good 占比 %。
- **评分**：每指标 p75>NI → +12；p75>good → +6；再 `+max(0, (100−avg_good)·0.4)`。

### 8.3 SRE 可靠性（--kind sre，--slo 默认 99.9）

字段（秒，epoch 或相对）：started/detected/acknowledged/resolved。统计窗口默认 max(resolved)−min(started)。

- MTTD=mean(detected−started)；MTTA=mean(acknowledged−detected)；MTTR=mean(resolved−detected)；MTBF=(window−downtime)/事件数。
- 可用性 %=(window−Σdowntime)/window；**nines = −log10(1−availability/100)**（100% 时记 99）。
- 错误预算：budget=(100−SLO)；消耗=max(0, 不可用率−budget)；`error_budget_remain = 100 − 消耗/budget·100`（下限 0）；**burn_rate = 不可用率/budget**。
- **评分**（pen 封顶 40/20/20）：avail<SLO → `min(40,(SLO−avail)·4)`；MTTR>3600 → `min(20,(MTTR/3600−1)·10)`；burn_rate>1 → `min(20,(burn−1)·15)`。

---

## 9. 工具 5：sysmetrics.py — USE/数据库

grade 90/80/70/60 档。输入每行一次采样。每指标输出 {mean, max, breach(超 warn 样本数), n}。

### 9.1 USE（--kind use，Brendan Gregg 三问）

16 项 spec `(label, key, warn, crit, higher_bad=True)`：

| 资源 | 指标 | warn | crit |
|---|---|---|---|
| CPU | cpu_util % | 80 | 95 |
| | cpu_runq 运行队列 | 4 | 8 |
| | cpu_throttle 节流 | 0.01 | 1 |
| | cpu_ecc_err | 0.01 | 1 |
| 内存 | mem_util % | 85 | 95 |
| | swap_pct % | 0.01 | 5 |
| | oom 次数 | 0.01 | 1 |
| | mem_err | 0.01 | 1 |
| 磁盘 | disk_util % | 80 | 95 |
| | disk_await ms | 20 | 50 |
| | disk_queue | 2 | 5 |
| | io_err | 0.01 | 1 |
| 网络 | net_util % | 80 | 95 |
| | net_drop | 0.01 | 1 |
| | net_retrans | 0.01 | 1 |
| | net_err | 0.01 | 1 |

breach=超 warn 样本数（higher_bad=True 时 v>warn）；crit 用于报告档位（实现中 breach 计数只看 warn）。**评分**：每指标有 breach → `pen += min(6, breach/n·10)`；score=100−pen。

### 9.2 DB（--kind db）

7 项：conn_pool_util(80,95)、replica_lag(30,120)、lock_waits(50,200)、deadlocks(0.01,1)、cache_hit(95,90,**higher_bad=False** → v<warn 计 breach，越高越好)、slow_query_rate(1,5)、storage(85,95)。**评分**：每指标 `pen += min(6, breach/n·12)`。

---

## 10. 工具 6：mleval.py — ML 质量/漂移

grade 90/80/70/60 档。drift 无 score/grade（只有 verdict；JSON fail-under 检查 getattr(score, 100) 恒过）。

### 10.1 quality

- **分类**（y_true/y_pred 均为 0/1）：混淆矩阵 TP/FP/FN/TN、accuracy、precision、recall、F1。
- **ROC-AUC**：有 y_score 时按 Mann-Whitney 式 O(N·M) 配对计数 `Σ(p>n?1:p==n?0.5:0)/(pos·neg)`（非排序算法）。
- **回归**：MAE、RMSE、R²=1−SSR/SST、MAPE%（非零真实值）。
- **生成/文本**：perplexity/hallucination/groundedness/toxicity 列直接均值汇总。
- **评分**：分类 → [acc, prec, rec, F1(+AUC 若非 NaN)] 均值；回归 → [max(0,R²), max(0,1−MAPE/100)] 均值；文本 → groundedness 正向、其余 1−x，均值。×100 得 0–100。

### 10.2 drift

- 分箱：**以 ref 的分位数等频切 10 bin**（edges = ref 的 0,10,…,100 分位，去重后补 min/max 保护）；_hist 线性映射到 bin + 下限 1e-6 防 log(0)，按频率归一。
- 指标：PSI=Σ(a−e)·ln(a/e)；KL=Σe·ln(e/a)；JS=0.5·KL(e||m)+0.5·KL(a||m)；Hellinger=√(0.5·Σ(√e−√a)²)；KS=ECDF 最大差（双样本，O(N·M) 朴素）。
- **判定（PSI）**：<0.1 无显著 / 0.1–0.25 中等 / >0.25 显著漂移。**坑：n<~100 时 PSI/JS 不稳定**（离散小样本飙高），至少几百样本才下漂移结论。

---

## 11. 工具 7：speechmetrics.py — TTS/STT

grade 90/80/70/60 档。RTF：优先读 rtf 字段，否则 proc_ms(→秒)/audio_sec。

### 11.1 STT（门槛可 --th-* 覆盖）

默认门槛：tail_silence p95≤350ms（对齐 P.A.L.M Vosk 实测 0.35s）、RTF≤1.0、WER≤10%、首 partial p95≤600ms。

- 输出 RTF mean/p95、实时占比、tail p95、first_partial p95、end2end p95、WER/CER mean。
- **评分**（pen 封顶 30/25/25/15）：
  - tail p95>350 → `min(30, (tail/350−1)·20)`；
  - rtf_mean>1 → `min(25, (rtf−1)·40)`；
  - WER>10 → `min(25, (wer/10−1)·15)`（仅当有 WER 列）；
  - first_partial p95>600 → `min(15, (p95/600−1)·10)`（仅当有列）。

### 11.2 TTS

默认门槛：RTF≤1.0、首音频字节 p95≤1200ms（LLM/GSV 首 token 500ms–1s 为相邻口径，可按场景调小）。

- 输出 RTF、首音频字节 p95、合成速率（char_count/audio_sec 均值，字/s）、MOS mean、伪影率 mean。
- **评分**（pen 封顶 30/25/20/15）：
  - rtf_mean>1 → `min(30, (rtf−1)·40)`；
  - first_audio p95>1200 → `min(25, (p95/1200−1)·15)`（仅当有列）；
  - MOS<4.0 → `min(20, (4−mos)·15)`（仅当有 MOS 列）；
  - artifact>1% → `min(15, artifact)`。

---

## 12. 工具 8：qoemetrics.py — 流媒体 QoE

grade 90/80/70/60 档。每条会话/流一行采样。SPEC 15 项 `(label, key, good, bad, higher_is_bad, weight)`：

| 指标 | good | bad | 方向 | 权重 w |
|---|---|---|---|---|
| fps | 25 | 15 | 低坏 | 2.0 |
| rebuffer_ratio % | 1 | 5 | 高坏 | 3.0 |
| rebuffer_evt_per_min | 0.5 | 2 | 高坏 | 2.0 |
| rtt ms | 150 | 300 | 高坏 | 1.5 |
| packet_loss % | 1 | 3 | 高坏 | 2.0 |
| jitter ms | 30 | 60 | 高坏 | 1.0 |
| bandwidth kbps | 2000 | 800 | 低坏 | 1.0 |
| frame_drops | 1 | 5 | 高坏 | 1.0 |
| av_sync_offset ms | 50 | 150 | 高坏 | 1.5 |
| startup ms (TTFF) | 2000 | 5000 | 高坏 | 2.0 |
| cdn_cache_hit % | 95 | 85 | 低坏 | 1.0 |
| abr_switches | 5 | 15 | 高坏 | 0.5 |
| freeze_count | 0 | 3 | 高坏 | 2.0 |
| freeze_dur s | 0.5 | 3 | 高坏 | 2.0 |
| playback_error_rate | 0.1 | 1 | 高坏 | 3.0 |

- 每指标输出 mean/max；越 good 档的样本比例 ratio；**pen += min(w·8, ratio·w·12)**（非线性：超得越多扣越多，但单指标单次封顶）。
- 达 bad 严重档的会话进 alerts 列表（带 mean/max 证据）。
- 综合 QoE 分 = 100 − Σpen；无数据列跳过（不惩罚）。

---

## 13. 跨工具已知口径注意点（供 LLM 评审重点）

以下为源码级客观事实，供评审者判断是否有意为之或需统一：

1. **等级分档两套并存**：codequal/latstat/dynprobe 用 90/75/60/45（A/B/C/D/E）；servemetrics/sysmetrics/mleval/qoemetrics/speechmetrics 内部用 90/80/70/60（代码内 `'A' if s>=90 else 'B' if s>=80 else ...`）。SKILL.md §指标数据契约宣称"等级口径全局一致 A≥90/B≥75/C≥60/D≥45/E<45"，与后五个脚本实际不符——跨工具比较等级需先归一。
2. **评分公式不跨脚本可比**：各脚本扣分斜率/封顶/权重自成体系（如 codequal duplication 超阈每点扣 8、qoemetrics 用 w·ratio 非线性、sysmetrics use/db 每项封顶 6 分）。SKILL.md 也明说"跨脚本不横向比绝对值"——评审可评估这是否足够安全。
3. **codequal 总分双口径**：默认 core（100 权）与 `--dims all`（125 权重新归一）分数直接可比性依赖归一化正确性；文件级 result.score 恒为 core 口径，而项目级可 all——逐文件分与项目总分口径可能不一致，是已知风险点。
4. **drift 无综合分**（只有 PSI 判读），mleval --fail-under 对其不生效（getattr 兜底 100）。
5. **sysmetrics breach 只按 warn 计数**，crit 参数当前仅作声明未进入扣分（USE 表格里 crit 是"展示档位"）；DB cache_hit 的 crit=90<warn=95 是反向语义的直观体现。
6. **codequal non-Python 精度标注为估算**（正则启发式，CC=关键字计数）；lizard 引擎可选但非默认。
7. **污点分析只到函数内**：SKILL.md 与 dynprobe docstring 都显式声明不跨函数/跨文件——"外部可达"标注可能低估真实可达性（如参数再传入 helper 再进 sink），判读需按"保守提示"使用。
8. **硬编码密钥规则靠命名猜测**（变量名/字典键），值侧不解析上下文（如公钥/示例 token 通过 placeholder 过滤兜底）——存在漏报与（低概率）误报空间。
9. **dynprobe concurrency 的 url/cmd 形态评分简化为只扣错误**（无死锁/饱和扣分），与白盒形态评分不等价。
10. **WER/CER/MOS/artifact 等列缺失时对应扣分项自动跳过**（`if wer and ...`），意味着不同数据宽度的评分不可直接横向比——判读应注明数据覆盖列。

---

*（本文档由源码直接提炼，所有公式/阈值/正则与 2026-09-04 快照一致；工具代码未改动。文档生成目的：供 LLM 评审算法设计、口径一致性、开源价值评估。）*
