# P.A.L.M 接口文档

> 本文档从代码自动提取（2026-08-12），与 `backend/app/` 实际注册路由一致。
> 共 **141** 个路由。所有端点默认挂 `require_api_token`（Bearer 鉴权），标注「无鉴权」的除外。

## 鉴权

- 请求头：`Authorization: Bearer <token>`，或查询参数 `?token=<token>`
- Token 由后端启动时生成，写入 `%TEMP%/palm_api_token`；`PALM_API_TOKEN` 环境变量可覆盖
- 权限引擎：默认拒绝，需先经 `/api/permissions` 授权

## BIOS 自检（_shared）

| GET | `/api/bios/status` | 权限：—（无鉴权） |

## 裁决引擎（adjudicator）

| GET | `/api/adjudicator/actions` | 权限：— |
| GET | `/api/adjudicator/ai-fallback/audit` | 权限：— |
| DELETE | `/api/adjudicator/ai-fallback/audit` | 权限：— |
| GET | `/api/adjudicator/ai-fallback/status` | 权限：—（无鉴权） |
| POST | `/api/adjudicator/ai-fallback/toggle` | 权限：— |
| POST | `/api/adjudicator/evaluate` | 权限：— |
| GET | `/api/adjudicator/events` | 权限：— |
| GET | `/api/adjudicator/operators` | 权限：— |
| GET | `/api/adjudicator/rules` | 权限：— |
| POST | `/api/adjudicator/rules` | 权限：— |
| PATCH | `/api/adjudicator/rules/{rule_id}` | 权限：— |
| DELETE | `/api/adjudicator/rules/{rule_id}` | 权限：— |

## Agent 框架（agent）

| GET | `/api/agent/affinity` | 权限：— |
| POST | `/api/agent/affinity` | 权限：— |
| POST | `/api/agent/ask-response` | 权限：— |
| GET | `/api/agent/characters` | 权限：— |
| POST | `/api/agent/characters` | 权限：— |
| POST | `/api/agent/characters/import` | 权限：— |
| GET | `/api/agent/characters/{character_id}` | 权限：— |
| DELETE | `/api/agent/characters/{character_id}` | 权限：— |
| POST | `/api/agent/dual-intervene` | 权限：— |
| POST | `/api/agent/dual-run` | 权限：— |
| GET | `/api/agent/dual-status` | 权限：— |
| GET | `/api/agent/events` | 权限：— |
| POST | `/api/agent/run` | 权限：— |
| GET | `/api/agent/tools` | 权限：— |

## 对话（chat）

| POST | `/api/chat` | 权限：— |
| GET | `/api/chat/file-support` | 权限：— |

## 会话记录（conversations）

| POST | `/api/conversations` | 权限：— |
| GET | `/api/conversations` | 权限：— |
| DELETE | `/api/conversations/{conv_id}` | 权限：conversations.delete |

## 加解密（crypto）

| POST | `/api/crypto/decrypt` | 权限：— |
| POST | `/api/crypto/decrypt-text` | 权限：— |
| POST | `/api/crypto/encrypt` | 权限：— |
| POST | `/api/crypto/encrypt-text` | 权限：— |
| GET | `/api/crypto/encryption` | 权限：— |
| POST | `/api/crypto/encryption` | 权限：— |
| GET | `/api/crypto/recovery-checksum` | 权限：— |
| GET | `/api/crypto/recovery-key` | 权限：— |
| POST | `/api/crypto/recovery-key/import` | 权限：— |
| GET | `/api/crypto/status` | 权限：—（无鉴权） |

## 文件（file）

| POST | `/api/files/upload` | 权限：file.write |
| GET | `/api/files/{file_id}/content` | 权限：file.read |

## 游戏生态（game）

| POST | `/api/game/award` | 权限：— |
| POST | `/api/game/checkin` | 权限：— |
| GET | `/api/game/items` | 权限：— |
| POST | `/api/game/purchase` | 权限：— |
| GET | `/api/game/shop` | 权限：— |
| GET | `/api/game/state` | 权限：— |
| GET | `/api/game/status` | 权限：—（无鉴权） |
| POST | `/api/game/unlock-item` | 权限：— |

## 模型供应商（models）

| POST | `/api/models/discover` | 权限：— |

## 运行监控（monitor）

| GET | `/api/monitor/effective-mode` | 权限：— |
| GET | `/api/monitor/game-running` | 权限：— |

## 离线模式（offline）

| GET | `/api/offline` | 权限：— |
| POST | `/api/offline` | 权限：— |

## Ollama（ollama）

| GET | `/api/ollama/catalog` | 权限：— |
| POST | `/api/ollama/deploy` | 权限：ollama.deploy_model |
| POST | `/api/ollama/download` | 权限：ollama.pull_model |
| GET | `/api/ollama/download/active/{model_key}` | 权限：— |
| GET | `/api/ollama/download/{job_id}` | 权限：— |
| POST | `/api/ollama/download/{job_id}/cancel` | 权限：— |
| GET | `/api/ollama/guide` | 权限：—（无鉴权） |
| GET | `/api/ollama/health` | 权限：—（无鉴权） |
| POST | `/api/ollama/import-gguf` | 权限：ollama.pull_model |
| GET | `/api/ollama/library` | 权限：— |
| POST | `/api/ollama/pull` | 权限：ollama.pull_model |
| POST | `/api/ollama/pull-stream` | 权限：ollama.pull_model |
| POST | `/api/ollama/upload` | 权限：ollama.deploy_model |

## 解析（parse）

| GET | `/api/parse/{job_id}` | 权限：— |
| GET | `/api/parse/{job_id}/result` | 权限：— |

## 兜底防御（safety）

| GET | `/api/safety/status` | 权限：—（无鉴权） |
| GET | `/api/safety/vault` | 权限：— |
| POST | `/api/safety/vault/clear` | 权限：— |
| POST | `/api/safety/vault/restore` | 权限：— |

## 定时任务（scheduler）

| GET | `/api/scheduler/jobs` | 权限：— |
| POST | `/api/scheduler/jobs` | 权限：— |
| GET | `/api/scheduler/jobs/{job_id}` | 权限：— |
| DELETE | `/api/scheduler/jobs/{job_id}` | 权限：— |
| POST | `/api/scheduler/jobs/{job_id}/toggle` | 权限：— |

## 受控自我进化（self_evolution）

| GET | `/api/self-evolution/audit` | 权限：— |
| POST | `/api/self-evolution/observe` | 权限：— |
| GET | `/api/self-evolution/patterns` | 权限：— |
| POST | `/api/self-evolution/propose` | 权限：— |
| POST | `/api/self-evolution/propose-skill` | 权限：— |
| POST | `/api/self-evolution/scan-and-propose` | 权限：— |
| GET | `/api/self-evolution/skills` | 权限：— |
| GET | `/api/self-evolution/skills/audit` | 权限：— |
| POST | `/api/self-evolution/skills/{name}/approve` | 权限：— |
| POST | `/api/self-evolution/skills/{name}/delete` | 权限：— |
| POST | `/api/self-evolution/skills/{name}/disable` | 权限：— |
| GET | `/api/self-evolution/slots` | 权限：— |
| POST | `/api/self-evolution/slots/close` | 权限：— |
| POST | `/api/self-evolution/slots/open` | 权限：— |
| GET | `/api/self-evolution/swaps` | 权限：— |
| POST | `/api/self-evolution/swaps` | 权限：— |
| GET | `/api/self-evolution/swaps/{swap_id}` | 权限：— |
| DELETE | `/api/self-evolution/swaps/{swap_id}` | 权限：— |
| POST | `/api/self-evolution/swaps/{swap_id}/activate` | 权限：— |
| POST | `/api/self-evolution/swaps/{swap_id}/approve` | 权限：— |
| POST | `/api/self-evolution/swaps/{swap_id}/deactivate` | 权限：— |
| POST | `/api/self-evolution/swaps/{swap_id}/dry-run` | 权限：— |
| GET | `/api/self-evolution/tools` | 权限：— |
| POST | `/api/self-evolution/tools/{tool_id}/approve` | 权限：— |
| POST | `/api/self-evolution/tools/{tool_id}/delete` | 权限：— |
| POST | `/api/self-evolution/tools/{tool_id}/disable` | 权限：— |

## 应用设置（settings）

| GET | `/api/settings` | 权限：— |
| POST | `/api/settings` | 权限：— |

## 存储池（storage）

| GET | `/api/storage/breakdown` | 权限：— |
| POST | `/api/storage/categories` | 权限：— |
| GET | `/api/storage/categories` | 权限：— |
| DELETE | `/api/storage/categories/{name}` | 权限：storage.delete |
| POST | `/api/storage/categories/{name}/cleanup` | 权限：storage.prune |
| PUT | `/api/storage/categories/{name}/quota` | 权限：storage.quota |
| POST | `/api/storage/categories/{name}/tier` | 权限：storage.quota |
| GET | `/api/storage/encryption` | 权限：— |
| GET | `/api/storage/events` | 权限：— |
| POST | `/api/storage/files` | 权限：— |
| GET | `/api/storage/files` | 权限：— |
| DELETE | `/api/storage/files/{file_id}` | 权限：storage.delete |
| POST | `/api/storage/files/{file_id}/archive` | 权限：storage.prune |
| GET | `/api/storage/files/{file_id}/content` | 权限：— |
| GET | `/api/storage/health` | 权限：—（无鉴权） |
| GET | `/api/storage/quota` | 权限：— |
| PUT | `/api/storage/quota` | 权限：storage.quota |
| GET | `/api/storage/stats` | 权限：— |
| PUT | `/api/storage/tiers/{tier}` | 权限：storage.quota |

## 语音识别（stt）

| GET | `/api/stt/keywords` | 权限：— |
| PUT | `/api/stt/keywords` | 权限：stt.listen |
| POST | `/api/stt/start` | 权限：stt.listen |
| GET | `/api/stt/status` | 权限：—（无鉴权） |
| POST | `/api/stt/stop` | 权限：stt.listen |

## 系统与权限（sys）

| GET | `/api/bricks` | 权限：— |
| POST | `/api/bulk` | 权限：— |
| POST | `/api/files/window-size` | 权限：— |
| POST | `/api/grant` | 权限：— |
| GET | `/api/health` | 权限：—（无鉴权） |
| GET | `/api/models` | 权限：— |
| POST | `/api/revoke` | 权限：— |

## 用量（usage）

| GET | `/api/token-usage` | 权限：— |
