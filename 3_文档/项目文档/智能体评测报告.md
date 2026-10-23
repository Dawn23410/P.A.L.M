# 智能体评测报告

> 📅 **时间线**
> - 2026-08-10：通用基准 + 代表题网络实测（同日）
> - 注：原始评测数据见同目录 JSON：智能体通用评测数据.json / 智能体代表题评测数据.json / 智能体备选评测数据.json

## Agent 通用基准测试（qwen3.5-flash）

- 时间：2026-08-10 20:39:28
- 模型：qwen3.5-flash
- 题库：P.A.L.M Agent 桌面视觉真实操作题库
- 抽题模式：one_per_category
- 通过：0/1

| 题目ID | 类型 | 来源 | 通过 | 耗时(s) | 工具调用 | 错误/失败原因 |
|---|---|---|---:|---:|---:|---|
| desktop_browser_search_ocr_basic | 桌面视觉浏览器搜索 | OSWorld/VisualAgentBench-inspired | False | 4.47 | 0/0 | provider 402: b'{"error":{"type":"gateway_error","code":"401008","message":"The free trial quota for the service has bee |

---


## Agent 代表题网络实测（kimi-k2.6）

- 时间：2026-08-10 18:29:59
- 网络模型：kimi-k2.6
- 说明：这是本地代表题实测，不是官方 GAIA/WebArena/OSWorld/SWE-bench/AgentBench 排行榜成绩。

| 类别 | 通过 | TTFT(s) | 总耗时(s) | 工具调用/结果 | 主要输出/错误 |
|---|---:|---:|---:|---:|---|
| GAIA代表题 | False | 0.027 | 76.303 | 7/7 | Agent 已达到最大迭代次数，请简化指令 |
| WebArena代表题 | False | 0.016 | 38.215 | 2/2 | 当前环境的网络访问工具受到离线管控限制，无法实际访问外部网页。因此，无法通过工具请求 `https://example.com` 获取页面标题及域名用途，也就无法提供您要求的实际访问结果。这是当前系统网络策略导致的限制。 |
| OSWorld代表题 | False | 0.018 | 49.191 | 3/3 | 文件创建与写入操作已执行，但读取文件时遇到系统拦截，返回提示“需用户确认”，无法自动完成读取步骤。因此无法通过读取确认内容。 根据已完成的写入操作及返回信息，确认写入内容为 OSWORLD_OK，但读取环节被阻断。 |
| SWE-bench代表题 | False | 0.016 | 58.937 | 7/7 | ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=8018): Read timed out. |
| AgentBench代表题 | False | 0.017 | 93.732 | 18/18 | Agent 已达到最大迭代次数，请简化指令 |

## 结论

- 通过数：0/5
- 工具调用数为0代表模型没有真正使用Agent工具，即使文本里声称完成也按失败处理。
- 失败项优先看工具调用链路、权限、模型function calling能力，而不是只看最终文本。

---
