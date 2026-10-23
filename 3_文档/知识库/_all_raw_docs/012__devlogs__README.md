# 记录归档（WorkBuddy / Trae）

- **归档时间**：2026-08-16
- **归档位置**：`docs/记录归档/`
- **归档方式**：移动（腾空间），仅记录文档，不含活数据库/应用配置

## 收录内容

### WorkBuddy（`记录归档/WorkBuddy/`）
| 目录 | 内容 | 体积 |
|---|---|---|
| sessions | 会话索引 | 0.1 MB / 357 文件 |
| memory | 对话记忆（*_memory.md） | 0.0 MB / 3 文件 |
| audit-log | 审计记录（2026-*.jsonl） | 14.9 MB / 38 文件 |
| traces | 每次会话的 trace | 3826.7 MB / 6893 文件 |
| logs | 每日运行日志 | 875.2 MB / 1613 文件 |

### Trae（`记录归档/Trae/`）
| 目录 | 内容 | 体积 |
|---|---|---|
| memory | Trae 记忆 | 0.2 MB / 28 文件 |
| assistant | 助手数据 | 0 文件 |
| work | 工作区数据 | 1.9 MB / 63 文件 |
| attachments | 附件 | 0.4 MB / 15 文件 |

## 严格排除（未移动，应用照常运行）
- WorkBuddy：`workbuddy.db`(-wal/-shm)、`settings.json`、`skills/`、`plugins/`、`connectors/` 等配置
- Trae：`AppData/Roaming/TRAE SOLO CN/`（整个活数据目录）、`~/.trae-cn` 的 `extensions/plugins/mcps/argv.json/installed-plugins.json` 等配置

## 已知残留
- `~/.workbuddy/logs` 残留约 66 个文件（约 295 MB）：因 WorkBuddy 正在运行、文件被进程锁定无法移动，属实时写入的当前日志。关闭 WorkBuddy 后可再次清空。
- `~/.workbuddy/memory` 被软件按服务端缓存自动重建（约 29 KB），不影响已归档的原始记忆。
