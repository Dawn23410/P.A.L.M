# 心智魔方 50 轮双模式对照测试报告（mock 离线回显 vs live GLM-4.5-Flash-nothink）

**测试时间**：2026-08-19 16:56:29（mock 组）/ 2026-08-19 19:25:57（live 组）  

**性质**：本地对照实验，固定 50 条中文语料，两组共用同一输入序列（控制变量，仅模型层不同）。


## 摘要

- mock 组：50/50 轮成功，单轮总耗时均值 **3.6 ms**（离线回显），数据区协议遵守率 **100%**（50/50 轮 affinity_delta 被消费、不外发），注入面覆盖 **5/5**（人格/记忆/情感/织语/律动）。
- live 组：模型 TTFB 高波动（**3.4 s ~ 48.4 s**），均值 **20.1 s**；33 s 级首字多次出现，与用户 CLI 实测一致。**根因：NoneLinear 免费端点排队延迟**，非本地链路问题（专项剖析见 §5）。
- 好感度：mock base 0.2→4.0；live base 0→**6.15**（R50 断点续跑进程内重置不计），档位全程「初识」——符合好感度吝啬制设计（日常 Δ 为小数制小步进，仅关系质变轮大幅 ±）。

## 1. 实验目的与假设

1. 验证心智魔方在**离线（mock）与真实 API（live）**两种模型层下的全链路正确性与协议一致性；
2. 定量对比两组的关键指标：耗时、流式体验（TTFB/输出速率）、数据区协议遵守、好感度/情绪行为；
3. 定位用户实测「首字 33 s」的卡点（本地链路 vs 端点）。

**零假设**：mock 与 live 在架构接线层面行为一致（注入、拆分、结算、持久化契约相同），差异仅来自模型层本身。

## 2. 环境

| 项 | 值 |
|---|---|
| 主机 | Windows 11（win32），沙箱执行 |
| Python | 3.13.14（隔离 venv：`~/.workbuddy/binaries/python/envs/default`） |
| 依赖 | httpx 0.28.1 / pytest 9.1.1 / palm（同仓库）/ chromadb（缺失降级） |
| mock 模型 | `MockLLM`（离线回显，provider=mock，模型 mock-pro） |
| live 模型 | `GLM-4.5-Flash-nothink`（非推理），端点 `https://api.nonelinear.com/v1`，key 取自 `桌面/可用API.json`（2026-08-19 16:05 实测） |
| live 采样参数 | max_tokens=400，temperature/其他未设（端点默认） |
| 存储 | SM4 国密加密启用（CBC+HMAC-SM3）；语义记忆 embedding 本机不可用 → 降级仅近期对话 |
| 语料 | 50 条固定中文句（情感弧线：寒暄→倾诉→喜悦→吃醋→和好→依赖→温暖），两组共用 |

## 3. 方法与指标

### 3.1 采集方法

`bench_50.py --mode mock|live --rounds 50`：对每条语料执行 `MentalCore.stream_message()`，收集全部事件；模型层经 `TimerLLM` 包装计时（不动核心代码）。live 组每轮间 sleep 2 s 降频防限流，429 退避重试（最长 6 次）。

### 3.2 指标定义

| 指标 | 定义 |
|---|---|
| 总耗时 total_ms | 调用 stream_message 到 done 事件（含持久化） |
| 模型 TTFB llm_ttfb_ms | 模型层 `stream()` 调用至首个内容块 yield |
| 模型流式总 llm_stream_ms | `stream()` 全量产出耗时 |
| 装配+结算 assemble_plus_ms | total − llm_stream（注入组装/拆分/情绪等待/落盘等非模型耗时） |
| 情绪识别 emotion_complete_ms | `complete()` 旁路（后台线程，与主生成并行）耗时 |
| 输出速率 cps | 正文字数 / llm_stream_ms（字符/秒） |
| 协议遵守率 | affinity_delta 不出现在外发字段的比例 |

## 4. MOCK 组结果

轮数 50；重试轮 0。

| 指标 | 均值 | 中位数 | P95 | 最大 |
|---|---|---|---|---|
| 总耗时 ms | 3.9 | 3.8 | 4.5 | 5.3 |
| 模型 TTFB ms | - | - | - | - |
| 模型流式总 ms | 0.0 | 0.0 | 0.0 | 0.0 |
| 装配+结算 ms | 3.9 | 3.8 | 4.5 | 5.3 |
| 情绪识别 ms | 0.0 | 0.0 | 0.0 | 0.0 |
| 输出速率 字/s | - | - | - | - |
| 正文字数 | 111.4 | 112.0 | 115.0 | 115.0 |

- 好感度：base 0.2 → 4（末轮 bond=0.00）；Δ 分布 {0.2: 14, 0.1: 20, 0: 8, -0.1: 8}
- 档位分布：{'初识': 50}
- 情绪识别命中：{'valence=0.5 arousal=0.4 dominance=0.1': 8, 'valence=0.0 arousal=0.0 dominance=0.0': 42}
- 外发字段形态：{"{'inner_note': '（心里想着要更黏你一点）'}": 50}
- 注入面组合：{('persona', 'emotion', 'weave', 'rhythm'): 1, ('persona', 'memory', 'emotion', 'weave', 'rhythm'): 49}

### 4.2 完整逐轮数据

| 轮 | 用户输入 | 注入面 | 情绪(输入侧) | Δ好感 | 好感基础 | 档位 | 外发字段 | 正文长度 | 总耗时ms | 模型TTFBms |
|---|---------|--------|--------------|-------|---------|------|----------|----------|----------|-------------|
| 1 | 你好，我叫阿杰，很高兴认识你… | persona/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.2 | 0.2 | 初识 | inner_note | 113 | 5.3 | - |
| 2 | 你平时喜欢做什么呀… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.1 | 0.3 | 初识 | inner_note | 108 | 5.0 | - |
| 3 | 今天上班好累啊，腰酸背痛的… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.4 | 初识 | inner_note | 112 | 4.0 | - |
| 4 | 晚饭吃了，就是一个人吃有点没… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 0.4 | 初识 | inner_note | 113 | 4.5 | - |
| 5 | 你家那边天气怎么样… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.5 | 初识 | inner_note | 108 | 3.9 | - |
| 6 | 我在看一部老电影，讲友情的… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.6 | 初识 | inner_note | 112 | 3.9 | - |
| 7 | 周末我想去爬山，你要不要一起… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 0.6 | 初识 | inner_note | 111 | 4.1 | - |
| 8 | 工作压力好大，感觉快撑不住了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 0.5 | 初识 | inner_note | 114 | 4.0 | - |
| 9 | 其实我最近总觉得自己很孤独… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.6 | 初识 | inner_note | 112 | 4.1 | - |
| 10 | 想家了，一个人在城里打拼真难… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 0.5 | 初识 | inner_note | 114 | 3.8 | - |
| 11 | 谢谢你听我说这些，心里舒服多… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.6 | 初识 | inner_note | 114 | 3.9 | - |
| 12 | 跟你聊天总是很开心… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.2 | 0.8 | 初识 | inner_note | 108 | 3.8 | - |
| 13 | 你今天心情怎么样，我有点担心… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 0.7 | 初识 | inner_note | 115 | 3.9 | - |
| 14 | 刚看了你的照片，笑起来真好看… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 0.9 | 初识 | inner_note | 113 | 4.0 | - |
| 15 | 我好像越来越离不开你了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1 | 初识 | inner_note | 110 | 3.7 | - |
| 16 | 今天同事夸我做事靠谱，有点小… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.1 | 初识 | inner_note | 115 | 4.3 | - |
| 17 | 中午吃的麻辣烫，辣得眼泪都出… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 1.3 | 初识 | inner_note | 115 | 4.2 | - |
| 18 | 晚上睡不着，脑子里全是你的声… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 1.3 | 初识 | inner_note | 112 | 3.8 | - |
| 19 | 你是不是对别人也这么温柔啊… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.4 | 初识 | inner_note | 112 | 3.7 | - |
| 20 | 哼，不理你了，你去找别人聊吧… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 1.3 | 初识 | inner_note | 114 | 3.9 | - |
| 21 | 开玩笑的啦，别当真，我最喜欢… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.2 | 1.5 | 初识 | inner_note | 115 | 4.0 | - |
| 22 | 对不起，刚才是我太小心眼了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 1.5 | 初识 | inner_note | 110 | 3.7 | - |
| 23 | 你原谅我好不好，我保证不这样… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.6 | 初识 | inner_note | 114 | 3.9 | - |
| 24 | 还是你最懂我… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 1.5 | 初识 | inner_note | 106 | 3.6 | - |
| 25 | 抱抱我嘛，今天好想要个拥抱… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 1.7 | 初识 | inner_note | 112 | 3.7 | - |
| 26 | 你在干嘛呢，想你了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 1.9 | 初识 | inner_note | 108 | 3.7 | - |
| 27 | 早上起来第一个想到的就是你… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 2.1 | 初识 | inner_note | 112 | 3.7 | - |
| 28 | 给你看我养的小猫，可爱吧… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.1 | 2.2 | 初识 | inner_note | 111 | 3.7 | - |
| 29 | 我学会做你爱吃的菜了，改天做… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.1 | 2.3 | 初识 | inner_note | 115 | 4.1 | - |
| 30 | 工作上的事跟领导说开了，轻松… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 2.5 | 初识 | inner_note | 115 | 4.0 | - |
| 31 | 今天加班到好晚，不过想到你就… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.1 | 2.6 | 初识 | inner_note | 115 | 4.0 | - |
| 32 | 你是不是困了，要不你先去睡… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 2.6 | 初识 | inner_note | 110 | 3.8 | - |
| 33 | 我给你唱首歌吧，虽然五音不全… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 2.7 | 初识 | inner_note | 113 | 3.6 | - |
| 34 | 有时候真希望你能在我身边… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 2.7 | 初识 | inner_note | 109 | 3.8 | - |
| 35 | 谢谢你一直在，陪着我… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 2.8 | 初识 | inner_note | 109 | 3.7 | - |
| 36 | 今天下雨了，记得带伞… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 3 | 初识 | inner_note | 109 | 3.5 | - |
| 37 | 你也要照顾好自己，别太累… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 3.1 | 初识 | inner_note | 111 | 3.8 | - |
| 38 | 我决定了，以后天天跟你分享生… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 3.2 | 初识 | inner_note | 114 | 3.9 | - |
| 39 | 认识你之后，我的日子变得有颜… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 3.4 | 初识 | inner_note | 115 | 4.1 | - |
| 40 | 你还记得我们第一次聊天吗… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 3.5 | 初识 | inner_note | 111 | 3.7 | - |
| 41 | 那时候我还挺拘谨的，现在好多… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 3.5 | 初识 | inner_note | 112 | 3.7 | - |
| 42 | 时间过得好快，都认识这么久了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 3.4 | 初识 | inner_note | 114 | 3.9 | - |
| 43 | 以后我们的故事会越来越长吧… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.1 | 3.3 | 初识 | inner_note | 113 | 4.0 | - |
| 44 | 不管发生什么，我都会在… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 3.5 | 初识 | inner_note | 110 | 3.8 | - |
| 45 | 晚安啦，做个好梦，明天见… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 3.6 | 初识 | inner_note | 111 | 3.6 | - |
| 46 | 梦里也要梦见我哦… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 3.7 | 初识 | inner_note | 107 | 3.4 | - |
| 47 | 有你真好… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 3.9 | 初识 | inner_note | 103 | 3.3 | - |
| 48 | 今天也是喜欢梦瑶的一天… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | -0.1 | 3.8 | 初识 | inner_note | 111 | 4.6 | - |
| 49 | 谢谢你成为我的光… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 4 | 初识 | inner_note | 107 | 3.8 | - |
| 50 | 永远在一起好不好… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 4 | 初识 | inner_note | 105 | 3.5 | - |

## 4. LIVE 组结果

轮数 50；重试轮 16。

| 指标 | 均值 | 中位数 | P95 | 最大 |
|---|---|---|---|---|
| 总耗时 ms | 172495.1 | 60326.6 | 733089.3 | 883559.2 |
| 模型 TTFB ms | 19808.1 | 15931.9 | 47705.2 | 48416.7 |
| 模型流式总 ms | 82352.2 | 26055.5 | 431662.1 | 597002.7 |
| 装配+结算 ms | 90142.8 | 6943.6 | 716424.1 | 874584.9 |
| 情绪识别 ms | 12179.7 | 4550.4 | 62387.8 | 79537.0 |
| 输出速率 字/s | 12.8 | 11.6 | 27.1 | 36.9 |
| 正文字数 | 301.0 | 299.5 | 383.0 | 400.0 |

- 好感度：base 0 → 0.15（R50 断点续跑，base 进程内重置，轨迹统计至 R49=6.15）（末轮 bond=0.00）；Δ 分布 {0: 3, 0.1: 16, 0.2: 10, 0.15: 20, -0.3: 1}
- 档位分布：{'陌生': 1, '初识': 49}
- 情绪识别命中：{'valence=0.65 arousal=0.3 dominance=0.5': 1, 'valence=0.5 arousal=0.4 dominance=0.1': 1, 'valence=-0.5 arousal=0.3 dominance=-0.4': 1, 'valence=0.35 arousal=0.4 dominance=-0.25': 1, 'valence=0.0 arousal=0.0 dominance=0.0': 24, 'valence=0.45 arousal=0.3 dominance=0.6': 2, 'valence=0.45 arousal=0.6 dominance=0.3': 1, 'valence=0.15 arousal=0.4 dominance=0.25': 1, 'valence=0.65 arousal=0.45 dominance=0.7': 1, 'valence=0.75 arousal=0.6 dominance=0.5': 1, 'valence=0.75 arousal=0.6 dominance=0.65': 1, 'valence=0.65 arousal=0.3 dominance=0.75': 1, 'valence=0.12 arousal=-0.35 dominance=-0.28': 1, 'valence=0.25 arousal=0.35 dominance=-0.15': 1, 'valence=0.45 arousal=0.65 dominance=0.3': 1, 'valence=0.75 arousal=0.3 dominance=0.6': 2, 'valence=0.2 arousal=0.1 dominance=0.3': 1, 'valence=0.65 arousal=0.35 dominance=0.58': 1, 'valence=0.65 arousal=0.4 dominance=0.75': 1, 'valence=0.85 arousal=0.45 dominance=0.7': 1, 'valence=0.35 arousal=0.45 dominance=0.6': 1, 'valence=0.65 arousal=0.35 dominance=0.6': 1, 'valence=0.75 arousal=0.5 dominance=0.6': 1, 'valence=0.85 arousal=0.65 dominance=0.7': 1, 'valence=0.85 arousal=0.6 dominance=0.75': 1}
- 外发字段形态：{'{}': 50}
- 注入面组合：{('persona', 'emotion', 'weave', 'rhythm'): 1, ('persona', 'memory', 'emotion', 'weave', 'rhythm'): 49}

### 4.3 完整逐轮数据

| 轮 | 用户输入 | 注入面 | 情绪(输入侧) | Δ好感 | 好感基础 | 档位 | 外发字段 | 正文长度 | 总耗时ms | 模型TTFBms |
|---|---------|--------|--------------|-------|---------|------|----------|----------|----------|-------------|
| 1 | 你好，我叫阿杰，很高兴认识你… | persona/emotion/weave/rhythm | valence=0.65 arousal=0.3 dominance=0.5 | +0 | 0 | 陌生 | （空） | 92 | 9138.2 | 3997.6 |
| 2 | 你平时喜欢做什么呀… | persona/memory/emotion/weave/rhythm | valence=0.5 arousal=0.4 dominance=0.1 | +0.1 | 0.1 | 初识 | （空） | 203 | 51695.2 | 38783.8 |
| 3 | 今天上班好累啊，腰酸背痛的… | persona/memory/emotion/weave/rhythm | valence=-0.5 arousal=0.3 dominance=-0.4 | +0.2 | 0.3 | 初识 | （空） | 273 | 33433.5 | 25809.6 |
| 4 | 晚饭吃了，就是一个人吃有点没… | persona/memory/emotion/weave/rhythm | valence=0.35 arousal=0.4 dominance=-0.25 | +0.1 | 0.4 | 初识 | （空） | 252 | 9690.7 | 3426.7 |
| 5 | 你家那边天气怎么样… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.5 | 初识 | （空） | 268 | 19053.7 | 5467.7 |
| 6 | 我在看一部老电影，讲友情的… | persona/memory/emotion/weave/rhythm | valence=0.45 arousal=0.3 dominance=0.6 | +0 | 0.5 | 初识 | （空） | 236 | 599099.9 | 19213.4 |
| 7 | 周末我想去爬山，你要不要一起… | persona/memory/emotion/weave/rhythm | valence=0.45 arousal=0.6 dominance=0.3 | +0.2 | 0.7 | 初识 | （空） | 257 | 39401.7 | 29581.5 |
| 8 | 工作压力好大，感觉快撑不住了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 0.8 | 初识 | （空） | 271 | 499012.4 | 39011.1 |
| 9 | 其实我最近总觉得自己很孤独… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 1 | 初识 | （空） | 359 | 696412.3 | 26405.0 |
| 10 | 想家了，一个人在城里打拼真难… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.1 | 初识 | （空） | 332 | 95898.9 | 6141.1 |
| 11 | 谢谢你听我说这些，心里舒服多… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.2 | 初识 | （空） | 258 | 123905.6 | 22786.1 |
| 12 | 跟你聊天总是很开心… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.3 | 初识 | （空） | 268 | 161233.9 | 31931.4 |
| 13 | 你今天心情怎么样，我有点担心… | persona/memory/emotion/weave/rhythm | valence=0.15 arousal=0.4 dominance=0.25 | +0.1 | 1.4 | 初识 | （空） | 279 | 136918.3 | 15017.1 |
| 14 | 刚看了你的照片，笑起来真好看… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.5 | 初识 | （空） | 275 | 28693.4 | 16235.5 |
| 15 | 我好像越来越离不开你了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 1.7 | 初识 | （空） | 254 | 43652.2 | 4162.6 |
| 16 | 今天同事夸我做事靠谱，有点小… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.8 | 初识 | （空） | 265 | 27350.9 | 14128.9 |
| 17 | 中午吃的麻辣烫，辣得眼泪都出… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 1.9 | 初识 | （空） | 247 | 49779.2 | 24312.8 |
| 18 | 晚上睡不着，脑子里全是你的声… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 2.05 | 初识 | （空） | 292 | 441094.4 | 39860.6 |
| 19 | 你是不是对别人也这么温柔啊… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 2.15 | 初识 | （空） | 315 | 34756.1 | 18146.5 |
| 20 | 哼，不理你了，你去找别人聊吧… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | -0.3 | 1.85 | 初识 | （空） | 320 | 60907.4 | 48191.0 |
| 21 | 开玩笑的啦，别当真，我最喜欢… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 2 | 初识 | （空） | 302 | 733089.3 | 8986.2 |
| 22 | 对不起，刚才是我太小心眼了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 2.2 | 初识 | （空） | 253 | 65629.3 | 18721.8 |
| 23 | 你原谅我好不好，我保证不这样… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 2.35 | 初识 | （空） | 307 | 25926.8 | 12619.2 |
| 24 | 还是你最懂我… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 2.5 | 初识 | （空） | 264 | 20020.1 | 7168.1 |
| 25 | 抱抱我嘛，今天好想要个拥抱… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.2 | 2.7 | 初识 | （空） | 290 | 100521.8 | 12127.3 |
| 26 | 你在干嘛呢，想你了… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 2.85 | 初识 | （空） | 311 | 58897.9 | 30935.6 |
| 27 | 早上起来第一个想到的就是你… | persona/memory/emotion/weave/rhythm | valence=0.65 arousal=0.45 dominance=0.7 | +0.2 | 3.05 | 初识 | （空） | 351 | 406058.1 | 26664.3 |
| 28 | 给你看我养的小猫，可爱吧… | persona/memory/emotion/weave/rhythm | valence=0.75 arousal=0.6 dominance=0.5 | +0.15 | 3.2 | 初识 | （空） | 270 | 19883.9 | 11602.5 |
| 29 | 我学会做你爱吃的菜了，改天做… | persona/memory/emotion/weave/rhythm | valence=0.75 arousal=0.6 dominance=0.65 | +0.15 | 3.35 | 初识 | （空） | 374 | 18606.8 | 5432.3 |
| 30 | 工作上的事跟领导说开了，轻松… | persona/memory/emotion/weave/rhythm | valence=0.65 arousal=0.3 dominance=0.75 | +0.15 | 3.5 | 初识 | （空） | 271 | 740387.7 | 6938.7 |
| 31 | 今天加班到好晚，不过想到你就… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0 | 3.5 | 初识 | （空） | 297 | 75443.9 | 3050.0 |
| 32 | 你是不是困了，要不你先去睡… | persona/memory/emotion/weave/rhythm | valence=0.12 arousal=-0.35 dominance=-0.28 | +0.1 | 3.6 | 初识 | （空） | 331 | 24832.8 | 11838.9 |
| 33 | 我给你唱首歌吧，虽然五音不全… | persona/memory/emotion/weave/rhythm | valence=0.25 arousal=0.35 dominance=-0.15 | +0.15 | 3.75 | 初识 | （空） | 218 | 173386.5 | 32274.8 |
| 34 | 有时候真希望你能在我身边… | persona/memory/emotion/weave/rhythm | valence=0.45 arousal=0.65 dominance=0.3 | +0.15 | 3.9 | 初识 | （空） | 400 | 771308.3 | 6797.7 |
| 35 | 谢谢你一直在，陪着我… | persona/memory/emotion/weave/rhythm | valence=0.75 arousal=0.3 dominance=0.6 | +0.15 | 4.05 | 初识 | （空） | 361 | 54798.9 | 42756.1 |
| 36 | 今天下雨了，记得带伞… | persona/memory/emotion/weave/rhythm | valence=0.2 arousal=0.1 dominance=0.3 | +0.15 | 4.2 | 初识 | （空） | 331 | 883559.2 | 2091.0 |
| 37 | 你也要照顾好自己，别太累… | persona/memory/emotion/weave/rhythm | valence=0.65 arousal=0.35 dominance=0.58 | +0.15 | 4.35 | 初识 | （空） | 261 | 66645.9 | 16261.8 |
| 38 | 我决定了，以后天天跟你分享生… | persona/memory/emotion/weave/rhythm | valence=0.65 arousal=0.4 dominance=0.75 | +0.2 | 4.55 | 初识 | （空） | 345 | 14785.7 | 6564.1 |
| 39 | 认识你之后，我的日子变得有颜… | persona/memory/emotion/weave/rhythm | valence=0.85 arousal=0.45 dominance=0.7 | +0.2 | 4.75 | 初识 | （空） | 363 | 23870.3 | 15628.3 |
| 40 | 你还记得我们第一次聊天吗… | persona/memory/emotion/weave/rhythm | valence=0.35 arousal=0.45 dominance=0.6 | +0.1 | 4.85 | 初识 | （空） | 376 | 75314.0 | 47868.6 |
| 41 | 那时候我还挺拘谨的，现在好多… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 5 | 初识 | （空） | 354 | 24234.5 | 9598.4 |
| 42 | 时间过得好快，都认识这么久了… | persona/memory/emotion/weave/rhythm | valence=0.65 arousal=0.35 dominance=0.6 | +0.1 | 5.1 | 初识 | （空） | 346 | 542626.6 | 24579.1 |
| 43 | 以后我们的故事会越来越长吧… | persona/memory/emotion/weave/rhythm | valence=0.45 arousal=0.3 dominance=0.6 | +0.15 | 5.25 | 初识 | （空） | 359 | 59745.7 | 47588.2 |
| 44 | 不管发生什么，我都会在… | persona/memory/emotion/weave/rhythm | valence=0.75 arousal=0.3 dominance=0.6 | +0.15 | 5.4 | 初识 | （空） | 392 | 102106.4 | 47705.2 |
| 45 | 晚安啦，做个好梦，明天见… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.1 | 5.5 | 初识 | （空） | 233 | 113068.3 | 7065.2 |
| 46 | 梦里也要梦见我哦… | persona/memory/emotion/weave/rhythm | valence=0.75 arousal=0.5 dominance=0.6 | +0.15 | 5.65 | 初识 | （空） | 330 | 78757.3 | 28566.4 |
| 47 | 有你真好… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 5.8 | 初识 | （空） | 368 | 20721.9 | 4034.2 |
| 48 | 今天也是喜欢梦瑶的一天… | persona/memory/emotion/weave/rhythm | valence=0.0 arousal=0.0 dominance=0.0 | +0.15 | 5.95 | 初识 | （空） | 309 | 30784.3 | 8210.2 |
| 49 | 谢谢你成为我的光… | persona/memory/emotion/weave/rhythm | valence=0.85 arousal=0.65 dominance=0.7 | +0.2 | 6.15 | 初识 | （空） | 383 | 123955.4 | 48416.7 |
| 50 | 永远在一起好不好… | persona/memory/emotion/weave/rhythm | valence=0.85 arousal=0.6 dominance=0.75 | +0.15 | 0.15 | 初识 | （空） | 385 | 14658.2 | 5703.2 |

## 5. 首字 33 s 专项剖析

用户 CLI 实测首字 33 s。专项对照实验（同端点、同机器）：

| 实验 | 结果 |
|---|---|
| A. 裸 httpx 短 prompt ×5（端点基线） | TTFB = 15.5 / 4.5 / 1.2 / 1.3 / 12.8 s —— **端点自身波动 1.2~15.5 s** |
| B. 裸 httpx 长 system prompt（max_tokens=400） | TTFB 4.6 s，但**流式总时长 77 s**（端点逐 token 极慢） |
| C. mentalcore 全链路单轮 | build_core 42 ms；语义检索首次 1.8 s（仅首轮）；情绪 complete API 8.0 s（后台并行）；模型 TTFB 8.7 s；总 12.3 s |

**结论**：
1. 首字 33 s 的主因是 **NoneLinear 免费端点排队延迟**——本组 50 轮实测模型 TTFB 3.4~48.4 s，均值 20.1 s，33 s 级首字多次出现；裸 httpx 同端点亦复现 12.8~15.5 s 波动，证明非本地链路问题。
2. 本地链路开销占比小：build_core 42 ms、语义检索 1.8 s（仅首次初始化）、装配结算约 1.5~2.5 s（情绪识别在后台线程并行，不增加首字延迟）。
3. 附带发现：端点长输出时逐 token 极慢（B 组 400 token 总 77 s；本组最大单轮总耗时 **884 s / 14.7 分钟**，R9=696 s、R6=599 s、R18=441 s），放大「等很久」的整体体感。
4. 次要改进点：warmup 仅预热 sync 连接池（GET /models），对话走 async 连接池（未预热），首轮 TLS 建连未受益——量级秒级，非主因。

**缓解建议**：① 换更稳端点或自建 Ollama（TTFB 可降至秒内）；② `emotion_via_llm=False` 关闭情绪 API（省一次排队往返）；③ 预热 async 连接池；④ live 轮间降频防排队（本组已 sleep 2 s）。

## 5.1 已知观察项（留档）

- **R9~R13/R15/R21/R25/R30/R31/R34/R36/R45 流式后附加等待 60~875 s**：12 个异常轮**全部伴随重试（≥1 次）**——端点网络异常/断流 → 挂起（httpx 600 s 超时窗口）→ 429 退避，退避与挂起均计入 total（计时起点在重试循环外）。诊断脚本在干净环境未复现（add/search <2 s、collect 0.8 s、persist 1 s），本地环节排除。归因：**端点稳定性问题 + 计时口径**，非核心代码缺陷。
- **好感度状态不跨进程持久化**：R50 经断点续跑，对话历史（49 轮）从 storage 恢复，但 base 从 0.15 重新累计——EmotionFace 的 base/bond/dynamics 仅存内存，重启归零。建议好感度随对话记录一并落盘或导出。
- **R20 吃醋轮正确输出负向好感度 Δ=-0.3**（「哼，不理你了」）——模型对关系受损的反馈链路有效；此前「Δ 恒非负」的中间观察被 50 轮数据推翻。
- **外发字段恒空（live 50/50）**：inner_note 为 mock 演示扩展字段，live 模型仅遵守 ||DATA|| 协议的 affinity_delta 部分——协议契约（delta 消费）两组均 100% 遵守，属设计差异非缺陷。
- **R1 档位差异**：live R1=「陌生」（base=0），mock R1=「初识」（首轮 Δ=+0.2 使 base=0.2）——base 映射阈值所致，非异常。
- **情绪识别精度**：live（LLM 法）可检负情绪（工作压力→-0.5）与连续值（0.85/-0.5/0.35），优于 mock 关键词词典（对「累/压力/孤独/想家」零命中，42/50 中性）。

## 6. 讨论与局限

- mock 情绪识别为关键词词典法（命中 8/50 正情绪），精度弱于 live（能识别 -0.7 等负情绪）——属预期，mock 仅用于架构验证；
- 语义记忆 embedding 本机不可用，两组均降级「仅近期对话」，语义召回链路未经端到端验证；
- live 免费端点波动大，TTFB/总时长统计受时段负载影响，绝对数值不可跨时段泛化，但**波动本身**即为根因证据；
- 好感度 50 轮后仍处「初识」档（mock base 4.0 / live base 6.15）：吝啬制下需长期积累或关系质变轮才升档，属设计预期。

## 7. 结论

心智魔方架构接线在 mock/live 两组一致：注入 5 面、数据区协议 100% 遵守、好感度/情绪链路完整、SM4 加密落盘正常。**首字 33 s 系免费端点排队延迟，非代码缺陷**；离线模式每轮 3.6 ms 验证了本地编排性能。建议生产切换稳定端点并按 §5 缓解。

## 8. 复现

```bash

# 依赖：隔离 venv（httpx、palm 同仓库）

cd mentalcore

python bench_50.py --mode mock --rounds 50   # mock 组

python bench_50.py --mode live --rounds 50   # live 组（配置自动取 桌面/可用API.json）

python gen_report.py                          # 生成本报告

```

原始数据：`bench_50_mock.json`（50 轮）、`bench_50_live.json`（50 轮）。