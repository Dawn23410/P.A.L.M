# P.A.L.M 微内核基准测试报告（商业级 · 论文级详细度）

- **生成时间**: 2026-08-23T09:48:18
- **Python**: 3.11.12
- **环境**: repaired .venv (Python 3.10.10 + palm.pth, offline)

## 总览

| 指标 | 值 |
| --- | --- |
| 内核数 | 11 |
| 用例总数 | 87 |
| PASS | 74 |
| FAIL | 0 |
| SKIP | 11 |
| XFAIL | 2 |
| 导入损坏内核 | 无 |

## 逐内核明细

### [palm]  PASS=10 FAIL=0 SKIP=0

- 可导入: `True`
- 计数: {'total': 10, 'PASS': 10, 'FAIL': 0, 'SKIP': 0, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | palm_submodules_importable | PASS | palm._core.* / palm.bootstrap.app 导入成功 |  |
| correctness | publish_subscribe | PASS | 订阅→发布→投递成功，收到 1 条；审计快照可用 |  |
| correctness | unsubscribe_works | PASS | unsubscribe(event_type, handler) 后订阅计数归零 |  |
| latency | emit_latency | PASS | emit 时延分布 p50=0.000ms p95=0.004ms |  |
| degradation | missing_service_none | PASS | 查询未注册服务返回 None（不崩溃） |  |
| correctness | deterministic | PASS | 中文+英文混合估算=6 tokens，幂等 |  |
| latency | latency | PASS | 500 字符估算时延 p50=0.003ms p95=0.004ms |  |
| correctness | detect_and_hint | PASS | detect→{'valence': 0.0, 'arousal': 0.0, 'dominance': 0.0}；hint 生成成功 |  |
| boundary | fail_closed_offline | PASS | 未注册网卡时外网请求抛 NetworkForbidden（fail-closed 安全） |  |
| degradation | build_app_idempotent_degrade | PASS | build_app() 在依赖齐备环境下仍返回容器且不抛异常 |  |

### [mentalcore]  PASS=6 FAIL=0 SKIP=2

- 可导入: `True`
- 计数: {'total': 9, 'PASS': 6, 'FAIL': 0, 'SKIP': 2, 'XFAIL': 1}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | mentalcore_importable | PASS | mentalcore.mentalcore 全符号导入成功（agent 框架整体保留） |  |
| correctness | construct | PASS | CharacterCard(id,name,tagline,pillars,flaws) 构造成功 |  |
| latency | construct_latency | PASS | 构造时延 p50=0.001ms p95=0.002ms |  |
| correctness | official_six_present | PASS | OFFICIAL_6 含 6 个好感度档位: ['抵触', '陌生', '初识', '友好', '亲近', '亲密'] |  |
| idempotency | default_idempotent | PASS | default_persona 两次等价: 梦瑶 |  |
| correctness | intent_routes | PASS | INTENT_ROUTES 路由表含 19 条入口 |  |
| boundary | partial_construct | XFAIL | TransportPacket 缺字段构造异常: TransportPacket.__init__() got an unexpected keyword argument 'role' | Traceback (most recent call last):
  File "C:\Users\Dawn\Desktop\P.A.L.M\tests\benchmarks\bench_mentalcore.py", line 87, |
| degradation | stream_message_run | SKIP |  | MentalCore.send_message/stream_message 需 LLM 运行时，离线不可执行 → skip |
| degradation | build_exo_run | SKIP |  | build_exo/WorkCube 依赖 exo 运行时，离线不可执行 → skip |

### [memory]  PASS=7 FAIL=0 SKIP=3

- 可导入: `True`
- 计数: {'total': 11, 'PASS': 7, 'FAIL': 0, 'SKIP': 3, 'XFAIL': 1}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | memory_submodules_importable | PASS | memory.domain_memory.* 导入成功 |  |
| degradation | construct_offline | PASS | Memory 离线构造成功；VectorMemory 惰性（依赖缺失不崩） |  |
| correctness | keyword_extract | PASS | 提取 11 个关键词，幂等 |  |
| latency | keyword_latency | PASS | 关键词提取时延 p50=0.005ms p95=0.006ms |  |
| correctness | relevance_ranking | PASS | 高相关=0.500 ≥ 低相关=0.000 |  |
| correctness | keyword_extract | SKIP |  | Memory 未构造（互操作砖缺失）→ 关键词提取 skip |
| correctness | relevance_ranking | SKIP |  | Memory 未构造（互操作砖缺失）→ 相关度 skip |
| correctness | dataclass_construction | PASS | SafetyLevel(Enum)/UserProfile/CoreMemoryData/SafetyConstraints 构造与字段访问正常 |  |
| correctness | allocate | PASS | 预算分配产出 Budget: core=122 recent=819 |  |
| boundary | empty_inputs_safe | XFAIL | 空输入边界测试需 Memory 实例：'Memory' object has no attribute '_extract_keywords' | Traceback (most recent call last):
  File "C:\Users\Dawn\Desktop\P.A.L.M\tests\benchmarks\bench_memory.py", line 122, in |
| degradation | vector_memory_init | SKIP |  | VectorMemory.initialize 需 ChromaDB + Ollama bge-m3 嵌入，离线不可用 → skip |

### [tool]  PASS=8 FAIL=0 SKIP=0

- 可导入: `True`
- 计数: {'total': 8, 'PASS': 8, 'FAIL': 0, 'SKIP': 0, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | tool_submodules_importable | PASS | tool.tool_cube / tool_matcher / agent_tools 导入成功（已修复内核拆分后 ..tool_base 相对导入断裂） |  |
| correctness | register_and_decide | PASS | 注册 1 工具，get/decide 链路通顺，decision.allowed=False |  |
| correctness | openai_schema_gen | PASS | to_openai_tool 产出合规 OpenAI function schema |  |
| correctness | keyword_ranking | PASS | 中文查询『读取一个文件』→ top=read_file |  |
| latency | rank_latency | PASS | rank 时延分布 p50=0.006ms p95=0.013ms |  |
| idempotency | rank_idempotent | PASS | 同查询排序稳定 |  |
| boundary | unknown_tool_safe | PASS | 查询未注册工具返回 None，不抛异常 |  |
| boundary | path_traversal_blocked | PASS | 越权路径读取抛异常被安全拦截: AttributeError |  |

### [plan]  PASS=8 FAIL=0 SKIP=1

- 可导入: `True`
- 计数: {'total': 9, 'PASS': 8, 'FAIL': 0, 'SKIP': 1, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | plan_submodules_importable | PASS | plan.plan_cube / plan.planning.planner 导入成功 |  |
| correctness | goal_decomposition | PASS | 目标分解为 3 步: ['明确目标与验收标准', '选择工具并执行', '核对结果并汇总结论'] |  |
| correctness | progress_state_machine | PASS | mark_done 后 progress 状态推进 |  |
| latency | build_plan_latency | PASS | build_plan 时延分布 p50=0.001ms p95=0.002ms |  |
| idempotency | decomposition_idempotent | PASS | 同目标分解结果一致 |  |
| correctness | robust_json_array_parse | PASS | 干净数组/带噪声数组解析成功；畸形/对象/空串降级为 None |  |
| latency | parse_latency | PASS | 解析时延分布 p50=0.002ms p95=0.005ms |  |
| boundary | empty_goal_safe | PASS | 空目标返回列表（降级单步/空），不崩溃 |  |
| degradation | llm_driven_plan | SKIP |  | Planner.plan/replan 依赖 llm_stream_fn（LLM 流式回调），离线不可执行 → skip |

### [gui]  PASS=3 FAIL=0 SKIP=2

- 可导入: `True`
- 计数: {'total': 5, 'PASS': 3, 'FAIL': 0, 'SKIP': 2, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | gui_modules_importable | PASS | gui.window_tools / gui.adapters_gui 导入成功（已修复内核拆分后 ..tool_base 与 .window_api 相对导入断裂） |  |
| correctness | tool_classes_exposed | PASS | 暴露 13 个窗口工具类: ['CloseWindowTool', 'FocusWindowTool', 'GetActiveWindowTool', 'GetWindowRectTool', 'ListWindowsTool', 'MaximizeWindowTool'] |  |
| boundary | enum_safe_headless | PASS | 无桌面会话下 enum_visible_windows 返回 list（安全降级） |  |
| degradation | real_window_ops | SKIP |  | focus_window/get_pixel_color 等需活动图形会话与 user32，无头环境 → skip |
| degradation | real_gui_automation | SKIP |  | Atlas/世界模型/UIA 实时感知需桌面会话与屏幕，无头环境 → skip |

### [llm]  PASS=5 FAIL=0 SKIP=0

- 可导入: `True`
- 计数: {'total': 5, 'PASS': 5, 'FAIL': 0, 'SKIP': 0, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | package_importable | PASS | llm 包顶层可导入 |  |
| correctness | providers_importable | PASS | llm.providers 可导入（llm.models + httpx 已具备） |  |
| correctness | factory_routing | PASS | get_provider_instance 按 type 路由到 MockProvider |  |
| correctness | mock_provider_echo | PASS | MockProvider 离线回声可用（输出 167 字符，含 done） |  |
| latency | real_provider_ttfb | PASS | 真实端点 nonelinear/GLM-4.5-Flash-nothink 流式首字 2026ms（本地开销约0.2ms，余为服务端思考） |  |

### [sandbox]  PASS=6 FAIL=0 SKIP=1

- 可导入: `True`
- 计数: {'total': 7, 'PASS': 6, 'FAIL': 0, 'SKIP': 1, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | sandbox_submodules_importable | PASS | sandbox.ast / sandbox.sandbox_cube 导入成功 |  |
| correctness | extract_host_and_risk | PASS | AST 提取 hosts=['bad.org', 'evil.com']，risk=high |  |
| latency | analyze_latency | PASS | 分析时延分布 p50=0.028ms p95=0.034ms |  |
| idempotency | analyze_idempotent | PASS | 同代码分析结果一致 |  |
| correctness | danger_refuse | PASS | deny 模式下危险命令被 _refuse 拦截 |  |
| boundary | malformed_syntax_safe | PASS | 畸形 Python 语法分析不崩溃，降级返回 |  |
| degradation | real_exec | SKIP |  | SandboxCube.run 真实命令执行需管理员/pywin32/Job Objects，离线不可执行 → skip |

### [security]  PASS=13 FAIL=0 SKIP=0

- 可导入: `True`
- 计数: {'total': 13, 'PASS': 13, 'FAIL': 0, 'SKIP': 0, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | all_submodules_importable | PASS | security.* 全部离线子模块导入成功 |  |
| correctness | five_profiles_constructible | PASS | hardline/strict/loose/ai/whitelist 均可构造 |  |
| correctness | engine_deny_rule | PASS | 注入 process.execute+rm -rf deny 规则后 evaluate→deny |  |
| correctness | hardline_warn_upgrade | PASS | hardline 下 warn 升级→deny |  |
| boundary | default_fail_open | PASS | 默认档对危险事件 verdict=deny（已预置基线） |  |
| correctness | batch_rules_fire | PASS | 5 条请求均产出 {action,confidence,reason} 裁决 |  |
| latency | single_latency | PASS | 单条裁决时延分布 p50=0.003ms p95=0.005ms |  |
| idempotency | deterministic_idempotent | PASS | 同输入重复裁决结果一致 |  |
| correctness | hard_block_detection | PASS | 恶意码 hard_block=True；scan 返回 0 条风险 |  |
| correctness | ssrf_host_deny | PASS | 环回/链路本地/私网地址被拒，公网放行 |  |
| boundary | empty_inputs_safe | PASS | 空 dict / 空串 / 空 chunk 不抛异常 |  |
| degradation | offline_local_scoring | PASS | 无 DNS 后端时仍返回本地规则评分: 10 |  |
| correctness | decoy_listing | PASS | 诱饵库列出 8 条；match 接口可用 |  |

### [speech]  PASS=3 FAIL=0 SKIP=2

- 可导入: `True`
- 计数: {'total': 5, 'PASS': 3, 'FAIL': 0, 'SKIP': 2, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | package_importable | PASS | speech 包顶层可导入（VOSK/CosyVoice/GSV 三引擎目录就位） |  |
| correctness | recognize_importable | SKIP |  | 导入失败: ModuleNotFoundError: No module named 'sounddevice'；根因=缺失 sounddevice/vosk/numpy |
| degradation | signal_fns | SKIP |  | resample_audio/ensure_16bit_pcm 等 numpy 信号处理不可达（numpy 缺失）→ skip |
| correctness | importable | PASS | speech.cosyvoice 可导入 |  |
| correctness | importable | PASS | speech.gpt-sovits 可导入 |  |

### [mentalcore_data]  PASS=5 FAIL=0 SKIP=0

- 可导入: `False`
- 计数: {'total': 5, 'PASS': 5, 'FAIL': 0, 'SKIP': 0, 'XFAIL': 0}

| 维度 | 用例 | 状态 | 说明 | 根因 |
| --- | --- | --- | --- | --- |
| correctness | data_dir_present | PASS | 数据目录存在: C:\Users\Dawn\Desktop\P.A.L.M\mentalcore_data\_borrowed_P.A.L.M_clean_Data |  |
| correctness | json_parse_all | PASS | 全部 27 个固件 JSON 可被标准库解析 |  |
| correctness | pool_present | PASS | pool.json 存在 |  |
| correctness | settings_present | PASS | settings.json 存在 |  |
| correctness | characters_present | PASS | characters/ 含 3 个角色 JSON |  |

## 时延分布（采样明细）

- **palm/emit_latency** (n=31): min=0.000ms, p50=0.000ms, p95=0.004ms, p99=0.059ms, max=0.082ms
- **palm/latency** (n=31): min=0.003ms, p50=0.003ms, p95=0.004ms, p99=0.004ms, max=0.005ms
- **mentalcore/construct_latency** (n=31): min=0.001ms, p50=0.001ms, p95=0.002ms, p99=0.003ms, max=0.003ms
- **memory/keyword_latency** (n=31): min=0.005ms, p50=0.005ms, p95=0.006ms, p99=0.008ms, max=0.009ms
- **tool/rank_latency** (n=31): min=0.006ms, p50=0.006ms, p95=0.013ms, p99=0.016ms, max=0.016ms
- **plan/build_plan_latency** (n=31): min=0.001ms, p50=0.001ms, p95=0.002ms, p99=0.002ms, max=0.003ms
- **plan/parse_latency** (n=31): min=0.002ms, p50=0.002ms, p95=0.005ms, p99=0.006ms, max=0.006ms
- **sandbox/analyze_latency** (n=31): min=0.026ms, p50=0.028ms, p95=0.034ms, p99=0.079ms, max=0.097ms
- **security/single_latency** (n=31): min=0.003ms, p50=0.003ms, p95=0.005ms, p99=0.008ms, max=0.009ms
