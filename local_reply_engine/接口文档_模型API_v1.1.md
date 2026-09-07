# 接口文档_模型API_本地对话引擎_v1.1

> 更新：2026-09-07 ｜ v1.2：+ 性能监控 `/metrics`（内存/存储/CPU）+ 热替换语料 `/reload`（支持用户自定义语料）
> 服务实现 `local_reply/server.py`，拉起脚本 `start_server.py` / `start_server.bat`

## 一、接口规范（P.A.L.M 模型类模块统一约定）

| 项 | 约定 |
|---|---|
| 地址 | `http://localhost:<port>` |
| 端口 | **≥ 10000**，**按档位固定**：full=`10000` / balanced=`10001` / lite=`10002` |
| 路径前缀 | `/p.a.l.m/models/api/` |
| 编码 | JSON（UTF-8） |

## 二、启动方式

```bash
python start_server.py                  # full 档, 端口 10000
python start_server.py --tier balanced  # 性能档, 端口 10001
python start_server.py --tier lite      # 节省档, 端口 10002
python start_server.py --tier lite --port 10010   # 显式覆盖端口
```

双击 `start_server.bat` 菜单选档（默认带 `--preload` 预热）。

参数：`--tier full|balanced|lite` ｜ `--host` ｜ `--port`（缺省按档位，<10000 拒绝启动）｜
`--preload`（启动即加载引擎；**预热失败服务照常启动**，心跳转 error 并带原因）。

## 三、心跳 `GET /p.a.l.m/models/api/heartbeat`

可带 `?tier=full|balanced|lite` 查询其他档位状态，缺省为本实例档位。

### 状态码定义

| code | status | 含义 |
|---|---|---|
| 0 | `ready` | 引擎已加载，可正常对话 |
| 1 | `not_ready` | 服务在线但引擎尚未加载（惰性，首请求或 `--preload` 后转 ready） |
| 2 | `error` | 引擎加载异常，`error` 字段带原因（如 `FileNotFoundError: 权重缺失`） |

### 响应示例

```json
{
  "code": 0,
  "status": "ready",
  "ready": true,
  "error": null,
  "tier": "full",
  "port": 10000,
  "service": "palm.models.mengyao_local",
  "api_prefix": "/p.a.l.m/models/api",
  "tiers_ready": ["full"],          // 本进程内已加载的档位
  "tier_errors": {},                // 各档位加载异常原因
  "thresholds": {"mock": 0.6, "semantic": 0.72},
  "uptime_s": 46.4
}
```

状态跃迁：`not_ready(1)` --首请求/--preload--> `ready(0)`；
加载抛异常 --> `error(2)`（原因同时出现在 `error` 与 `tier_errors`）。
心跳为纯只读，**不会触发引擎加载**。

## 四、其他端点

### 对话 `POST /p.a.l.m/models/api/chat`

```json
// 请求
{"text": "在吗", "history": [["你好","在的呢喵"]], "tier": "full"}
// tier 可省略, 缺省为本实例档位; history ≤20 轮; text 1-200 字(引擎内截 60)
// 响应
{"reply": "在的在的，猫娘一直都在呢喵", "confidence": 0.9827,
 "mode": "semantic", "tier": "full", "latency_ms": 15.2}
```

`mode`：semantic ｜ mock ｜ tool（天气实况，需联网）。`confidence` 低于档位阈值
（mock 0.60 / m3 0.72 / small 0.75）为兜底回复，调用方可按需接 LLM。

### 状态 `GET /p.a.l.m/models/api/stats?tier=`

上一轮调用（confidence / latency_ms / fallback）+ uptime。

### 重置 `POST /p.a.l.m/models/api/reset?tier=`

清空该档位引擎会话记忆（recent_replies / queries）与 last_call。

### 性能监控 `GET /p.a.l.m/models/api/metrics`

进程级开销快照，无需任何引擎加载，纯只读：

```json
{
  "uptime_s": 47.4,
  "process": {"rss_mb": 1894.7, "cpu_pct": 16.4, "threads": 2},
  "storage_mb": {
    "corpus_default": 0.6,   // 内置语料目录
    "data_default": 1179.9,  // 语义索引缓存（bge-m3 向量等）
    "weights": 582.9,        // 模型权重（bge_m3.onnx + tokenizer）
    "custom_corpus": 0.0     // 通过 PALM_CORPUS_DIR 指定的外部语料
  },
  "tiers": {
    "full": {"records": 2837, "mode": "semantic",
             "corpus_fp": "a8f90ddc", "corpus_dir": null}
  },
  "tier_errors": {},
  "last_call": {"full": {"confidence": 0.98, "mode": "semantic",
                        "latency_ms": 15.2, "fallback": false}}
}
```

- `process.rss_mb`：常驻物理内存（Windows 经 `K32GetProcessMemoryInfo`，非 Windows 为 `null`）。
- `process.cpu_pct`：自启动以来平均 CPU 占用百分比（CPU 秒 / 运行时长）。
- `storage_mb.*`：各目录磁盘占用（MB），便于评估语料/缓存/权重体积与增长。
- `tiers[*].corpus_fp`：语料指纹（内置语料文件名+大小的 sha256 前 8 位）。
  **换语料会改变指纹 → 自动隔离语义索引缓存，不会误用旧向量**（见 `/reload`）。

### 热替换语料 `POST /p.a.l.m/models/api/reload`

用新语料目录原子重建某档位引擎（在线换语料，无需重启服务）：

```json
// 请求体 ReloadIn
{"tier": "lite", "corpus_dir": "D:/corpus/my_gf", "data_dir": null}
// corpus_dir 须含 mengyao_hq_part*.jsonl；为空则校验失败 400
// 响应
{"tier": "lite", "corpus_dir": "D:/corpus/my_gf",
 "records": 2, "mode": "mock", "reloaded": true, "old_freed": false}
```

- 在档位锁内重建并替换引擎，**并发 `/chat` 安全**（替换瞬间短暂串行）。
- 索引缓存按 `corpus_fp` 隔离：`{tag}_{fp}.npy`，换语料后旧缓存不被复用；
  旧格式 `stitching_vectors_{tag}.npy` 若条目数匹配会平滑迁移。
- 复用优先级（同 `_resolve_corpus`）：请求显式 > 本档位已加载记忆 > 环境变量
  `PALM_CORPUS_DIR` / `PALM_DATA_DIR` > 引擎内置语料。
- 启动期指定：拉起脚本 `--corpus-dir / --data-dir`（会在 import server 前写环境变量）。
- **无单文件条数上限**：`load_persona_bank` 默认已不限条数。旧版曾静默截断每文件前 5000 条，
  换上单文件大体量外来语料会无声丢数据；现已去掉该上限，单文件可放数万条，
  多文件按 `mengyao_hq_part*.jsonl` 拆分同样全量加载。
- **已验证 2 万条外来语料**：`corpus_ordinary_20k/`（普通日常对话、无人格）热替换后
  `records=20000`、无崩溃；延迟 semantic 档中位 ~19ms（≈内置 1.2×）、
  mock 档中位 ~3ms（倒排索引优化后无大幅衰退），覆盖率 semantic 100% / mock ~96%。

## 五、错误码

| 状态码 | 场景 |
|---|---|
| 400 | tier 非法（非 full/balanced/lite） |
| 422 | 请求体校验失败（text 空/超长等，pydantic） |
| 500 | 引擎内部异常（detail 带原因；加载类异常同时记入心跳 tier_errors） |

## 六、其他模块接入示例

```python
import requests

BASE = "http://localhost:10000/p.a.l.m/models/api"   # full 档
hb = requests.get(f"{BASE}/heartbeat").json()
if hb["code"] == 0:                                   # 仅就绪时对话
    r = requests.post(f"{BASE}/chat", json={"text": "在吗"})
    print(r.json()["reply"])
elif hb["code"] == 2:
    print("引擎异常:", hb["error"])
```

## 七、已验证项（2026-09-07 实测）

- 档位独立端口：full=10000 / lite=10002 双实例并行，心跳 tier/port 字段正确
- 心跳三状态：未预热 not_ready(1) → 对话后 ready(0)；error(2) 分支注入验证（原因透传）
- 心跳不触发引擎加载；chat/stats/reset 省略 tier 时自动用本实例档位
- 天气工具链路（mode=tool）、多轮 history、非法 tier 400 均正常
- **并发安全**：20 并发 `/chat` 全 200、零空回复、回复多样（每档加锁串行化共享状态）

## 七-A、性能监控与语料热替换（v1.2 实测）

- **`/metrics` 监控**：full 预热实例返回 `rss_mb=1894.7`、`cpu_pct=16.4`、
  `threads=2`，storage 各目录体积（corpus_default/data_default/weights/custom_corpus）齐全；
  非 Windows 或 ctypes 失败优雅降级为 `null` 而非报错。
- **语料可替换**：`/reload` 用 2 条自定义语料（"讲个冷笑话"→企鹅段子）重建 lite 引擎，
  后续 `/chat` 命中新语料；指纹隔离生效（full=`a8f90ddc` / lite=`ba0a1840`，换目录即变）。
- **缓存隔离**：换语料后语义索引按 `corpus_fp` 重新生成，不会复用旧向量（杜绝"换汤不换药"）。
- **热替换并发安全**：`/reload` 在档位锁内原子替换，替换期间 `/chat` 仅短暂串行。

## 八、生产部署自检清单

### 代码层（已就绪 ✅）
| 项 | 状态 |
|---|---|
| 接口规范：localhost ≥10000 + `/p.a.l.m/models/api/` 前缀 + 心跳 | ✅ |
| 心跳状态码 0/1/2 区分 就绪/未就绪/异常+原因 | ✅ |
| 档位独立端口、多实例并行 | ✅ |
| 并发安全（每档锁，串行化引擎共享状态） | ✅ |
| 错误处理：400/422/500 + 预热失败不躺平 | ✅ |
| 默认绑定 127.0.0.1（不暴露公网） | ✅ |
| 依赖锁定 `requirements.txt` | ✅ |

### 运维层（部署前需补齐 ⚠️）
1. **进程守护**：当前无 supervisor，进程崩溃/OOM（full 档常驻 ~2.7GB）不会自启。
   由 P.A.L.M 进程管理统一接管 lifecycle，或加 systemd / supervisor。
2. **专用依赖环境**：本服务现跑在共享 venv，建议 `python -m venv .venv && pip install -r requirements.txt`，
   避免其他项目改 venv 连锁击穿。
3. **CORS**：默认未开。若 P.A.L.M 前端（浏览器）跨源调用需加 `CORSMiddleware`；
   纯 server-to-server（requests）无需。
4. **认证/限流**：localhost 内调可省；若监听非回环地址必须加 token 鉴权 + 限流。
5. **三实例资源**：同时起 full+balanced+lite 常驻约 3.5GB+ 内存，按机器余量规划。
6. **`/docs` 暴露**：默认开启 Swagger，生产可 `app = FastAPI(docs_url=None)` 关闭。
7. **内置监控**：`/metrics` 已提供内存(RSS)/CPU/存储快照，localhost 内调可直接轮询，
   无需额外 exporter；若要接入 Prometheus 等，按 `/metrics` 字段写采集器即可。

### 结论
代码层面**满足生产可用的定义范围**（被其他 P.A.L.M 砖块以 localhost 调用的本地模型模块）。
剩余均为部署/运维事项，非代码缺陷；按上方运维清单补齐后即可上线。

