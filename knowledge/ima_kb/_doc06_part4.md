# P.A.L.M 从零复刻指南（深度扩充一：启动脚本/故障排查手册）

> 承接《从零复刻指南》正文与扩充章 A-E。本部分给出：启动脚本详解（dev.py 逻辑）、故障排查手册（按症状定位）、以及运行期监控要点。

---

## 扩充章 F：启动脚本详解（dev.py/dev.bat）

### F.1 dev.py 逻辑（推断重构，供复刻参考）

```python
def main():
    ensure_dependencies()      # 依赖幂等安装（检查关键包 → 缺失安装）
    setup_logging(level="dev") # dev 实时日志（控制台输出）
    check_env()                # .env 检查（缺失提示）
    launch_backend()           # uvicorn 启动 FastAPI（:8005）
    # 可选：launch_frontend() / launch_voice() / launch_stt()
```

### F.2 dev.bat 要点

- 注释用 rem（不用 ::，防批处理解析踩坑）。
- 文件 CRLF 换行（LF 会被 cmd 误执行）。
- 依赖幂等：重复执行不重复安装。

### F.3 启动检查清单（复刻必做）

| # | 检查 | 命令/方法 |
|---|---|---|
| 1 | 装配幂等 | build_app() 两次调用无重复注册 |
| 2 | 14 服务可取 | container.get 逐个非 None |
| 3 | 端口监听 | 8005 可访问 |
| 4 | 前端加载 | 5173 或静态托管可访问 |
| 5 | 对话链路 | POST /api/chat 返回事件流 |
| 6 | 语音降级 | 未配置时 /api/stt/status 报缺失不崩 |

---

## 扩充章 G：故障排查手册（按症状定位）

### G.1 对话类故障

| 症状 | 可能原因 | 排查路径 | 修复 |
|---|---|---|---|
| 前端收不到流式 | CORS 未配置 | 检查 CORS_ALLOW_ORIGINS | 补来源 |
| 对话无响应 | 模型端点不可达 | 检查 settings.json customProviders | 换端点/降级 mock |
| 回复带角色语气（已关角色） | 三处注入点残留 | 检查系统提示/历史/工具上下文 | 补开关判断 |
| 长对话变慢 | 上下文未压缩 | 检查 P4 压缩触发 | 调压缩阈值 |
| 回答不成立 | 反思闸门未生效 | 检查 completion_gate | 开启 P3 |

### G.2 工具类故障

| 症状 | 可能原因 | 排查路径 | 修复 |
|---|---|---|---|
| 工具调用被拒 | 裁决 deny | 查 guardrail 日志 | 调档/加规则 |
| 敏感操作被询问 | permission 未授权 | 查 permissions.json | 授权 |
| 出网失败 | 网卡未注册 | 查 net 状态 | 注册网卡 |
| 代码执行被拦 | 沙箱 fail-closed | 查 sandbox_cube | 配置隔离 |
| ask_user 卡住 | 事件缺 id/未即时推送 | 查事件负载 | 补 id |

### G.3 数据类故障

| 症状 | 可能原因 | 排查路径 | 修复 |
|---|---|---|---|
| 设置保存失败 | Windows 文件锁 | 查错误日志（误报 CORS） | 重试/降级 |
| 记忆写入角色语气 | 污染检测未开 | 查 memory_writer | 开启检测 |
| 用量虚增 | 估算量入账 | 查 token_ledger | 只记 provider 真实量 |
| 删除后无法找回 | vault 未接入 | 查 delete_file 链路 | 接入 vault |

### G.4 心智核心故障

| 症状 | 可能原因 | 排查路径 | 修复 |
|---|---|---|---|
| selftest 失败 | 依赖缺失 | 查安装 | 补依赖 |
| 控制码无效 | 码值错误 | 查 CONTROL_USAGE | 用正确码 |
| mock 落盘 | persist 误开 | 查 build_core 参数 | persist=False + sem=None |
| Worker 不执行 | EXO 未接线 | 查 exo_broker | make_broker 注入 |
| 首字慢 | 端点排队 | 查 TTFB 指标 | 换端点/本地模型 |

### G.5 Windows 工程类故障

| 症状 | 原因 | 修复 |
|---|---|---|
| bat 执行怪异 | LF 换行 | 转 CRLF |
| :: 注释报错 | 批处理解析 | 改 rem |
| uiautomation 异常 | import 顺序 | 先 CoInitializeEx(STA) |
| 路径硬编码 | 环境差异 | 统一 paths.py |

---

## 扩充章 H：运行期监控要点

### H.1 监控面板（前端 monitor.html/overview.html）

- 14 服务状态（注册/降级）。
- 看门狗健康（子进程/服务）。
- 裁决审计（最近裁决事件）。
- 事件总线审计（最近 N 条）。

### H.2 指标采集

- usage_ledger：Token 账本（provider 口径）。
- gui_metrics：GUI 执行成功率/耗时。
- agent_traces.jsonl：Agent 轨迹。
- threat_data.json：威胁记录。

### H.3 保洁与健康

- housekeeping：定期清理临时文件/日志。
- 存储健康：quota/lifecycle/audit/health（存储面板）。
- watchdog：服务异常重启/告警。

---

## 扩充章 I：复刻验证基线（可执行脚本清单）

| 脚本 | 作用 | 基线 |
|---|---|---|
| 端点扫描 | 全量链路探测 | 163 端点无 500 |
| unit tests | 14 服务单元测试 | 7/8（修复遗留 1 项至 8/8） |
| e2e（8012） | 全链路 | 无业务 bug |
| selftest | mentalcore 自检 | 全过 |
| exo.selftest | 外骨骼自检 | 4 测全过 |
| bench_50 | 50 轮对照 | mock 3.9ms / 协议 100% |
| bench_100 | 100 轮实测 | 稳定（错误 <2%） |

---

## 扩充章 J：复刻后的日常维护

1. **归档治理**：新功能验证期不归档；稳定后归档（archive/ 不入库）。
2. **基准回归**：性能优化后跑 bench 对照（不包装数据）。
3. **安全审计**：新增外部引用网络核实；新增能力过裁决。
4. **文档同步**：架构变更先文档后代码（评审驱动）。
5. **备份策略**：重大变更前归档备份（Data/venv/git）。
