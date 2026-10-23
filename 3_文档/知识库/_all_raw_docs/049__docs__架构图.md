# P.A.L.M 项目架构图（全中文 · 含接口定义标准）

> 📅 **时间线**：2026-07 砖块架构落地后绘制；接口定义标准随 08-10 收口期代码最终核对。

# P.A.L.M 项目架构图
全中文 · 三层解耦 + 砖块主板 + 接口定义标准（依据 base.py / main.py / security.py / permission.py / client-infra.ts / 示例砖块 chat/brick.py 真实代码绘制）

## 一、总体架构（三层解耦）
桌面壳 PyWebView（JS→Python 桥） 注入 window.__API_BASE__ / __API_TOKEN__ React SPA（唯一客户端砖） UI 中枢 · 经 fetch 调用后端语义端点 不硬编码具体砖块，经 /api/bricks 发现 FastAPI（纯 HTTP 接口服务） 应用工厂 create_app() · 挂载砖块路由 统一异常处理器 · CORS · 请求日志 离线网关（gateway.py 切断外网） 砖块主板（BrickRegistry · 按总线 BusType 分组） CPU 槽编排主控agent SATA 槽持久化数据storage/memory PCIE 槽重计算/媒体stt/tts RAM 槽运行态易失usage/affinity BOARD 槽板载焊死chat/核心 CHIP 槽系统内置storage 芯片 插件砖（隔离 plugins/ 动态加载）：tts_sovits · qwen_tts · display(已搁置) | 其余内置砖：sandbox/file/chat/models/conversations/ollama/parse/crypto/offline/settings/adjudicator/roleplay/evolution/self_evolution/scheduler/game/safety/monitor 跨砖铁律：仅经 registry.get(name).capabilities.get(key) 交互，互不 import；缺失能力降级为 None。 CapabilitySlot：primary 出厂 + AI 替代实现 + 熔断回退（连续失败达阈值→自动回退并拉黑 degraded）。 BrickManifest：is_core（缺失即启动失败）/ is_enabled（可关闭）/ bus_type / is_streaming / can_accept_files。 HTTP / authedFetch 语义化端点 /api/* include_router（按 enabled 启停）

## 二、砖块总览（注册顺序 = 依赖顺序）

| 注册序  | 砖块           | 角色 / 关键能力                                  | 总线类别（语义） |
| ------- | -------------- | ------------------------------------------------ | ---------------- |
| 1       | sandbox        | 沙箱执行（底层域，须最先注册）                   | BOARD            |
| 2       | file           | 文件工具（限用户主目录）                         | SATA             |
| 3       | chat           | 流式对话入口 /api/chat（核心砖）                 | BOARD            |
| 4       | models         | 模型协议（capability: create_stream）            | PCIE             |
| 5       | conversations  | 会话存储（分页+审计）                            | SATA             |
| 6       | ollama         | 本地模型                                         | PCIE             |
| 7       | parse          | 文件→结构化文本                                  | PCIE             |
| 8       | crypto         | 加密（多因子密钥+MEK 轮转）                      | BOARD            |
| 9       | storage        | 存储芯片（介质层+管理芯片）                      | CHIP             |
| 10      | offline        | 离线模式（patch 出网链路）                       | BOARD            |
| 11      | settings       | 设置（字段校验+审计+版本号）                     | BOARD            |
| 12      | usage          | 用量配额台账（check_quota/record_usage）         | RAM              |
| 13      | adjudicator    | 裁决引擎（纯规则+AI 兜底）                       | BOARD            |
| 14      | roleplay       | 角色扮演引擎（memory/agent 依赖，须先注册）      | RAM              |
| 15      | affinity       | 好感度引擎                                       | RAM              |
| 16      | memory         | 记忆引擎（向量 bge-m3 + 五因子情绪）             | SATA             |
| 17      | agent          | 编排主控（CPU 槽，取 roleplay/memory/evolution） | CPU              |
| 18      | evolution      | 自主进化（依赖 agent 能力）                      | BOARD            |
| 19·插件 | tts_sovits     | 语音合成插件（经 agent.register_tool）           | PCIE             |
| 20·插件 | qwen_tts       | 语音合成插件（备用）                             | PCIE             |
| 21      | self_evolution | 受控自注册工具（须在 agent 后）                  | BOARD            |
| 22      | scheduler      | 定时任务（依赖 evolution.run_proactive）         | RAM              |
| 23      | game           | 游戏/星砂商城                                    | RAM              |
| 24      | safety         | 安全（H1-H4 加固）                               | BOARD            |
| 25      | monitor        | 运行监控（游戏检测/模式解析）                    | RAM              |
| 26      | stt            | 语音识别（独立子进程，事件总线广播）             | PCIE             |
| 27·插件 | display        | 显示层插件（已搁置，仅前端残留）                 | BOARD            |

注册顺序即依赖序；外部插件砖（tts_sovits/qwen_tts/display）隔离在 plugins/，经 _load_plugin 动态导入，缺失静默跳过。总线类别为语义展示（维护在各自 BrickManifest.bus_type），agent 明确为 CPU 槽，其余按职责归类。

## 三、接口定义标准（详细规范）

### ① 路由层规范
每个砖块定义独立 APIRouter(prefix="/api", tags=[...])，启用时由 main._mount_brick_routers 经 app.include_router 挂载；enabled=False 的可选砖不挂载。

```
router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat",
    dependencies=[Depends(require_api_token)])
async def chat(req: ChatRequest): ...

@router.get("/chat/file-support",
    dependencies=[Depends(require_api_token)])
async def chat_file_support(...): ...
```

UI 中枢经 GET /api/bricks 发现全部砖块及其 capabilities 键，不硬编码砖名。

### ② 鉴权标准（文件信息交换类端点）
启动生成一次性随机 Token（secrets.token_hex(32)），写入临时文件并注入前端 window.__API_TOKEN__。受保护端点挂 Depends(require_api_token)。

```
def require_api_token(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    # 校验 Authorization: Bearer <token>
    # 兼容 ?token= 供 <img>/<a download> 场景
    if not provided or not secrets.compare_digest(
            provided, _TOKEN):
        raise HTTPException(401, "无效或过期的 API Token")
```

仅 health 等免鉴权；Token 未初始化时不拦截。环境变量 PALM_API_TOKEN 可覆盖（开发用固定值）。

### ③ 权限引擎标准
砖块构造时经 permissions=[PermissionSpec(...)] 声明；敏感端点挂 Depends(require_permission(key))。未授权抛 PermissionDenied，由全局处理器转 403（绝不 500）。

```
class PermissionSpec:   # 蛇形 key + 中文 title
    key: str            # 如 file.delete
    title: str          # 面向用户的中文标题
    description: str    # 用途说明（知情权核心）
    risk: RiskLevel     # high/medium/low
    brick: str

def require_permission(key: str):
    def _dep():
        if not get_engine().is_granted(key):
            raise PermissionDenied(key)
    return _dep
```

状态 GRANTED/DENIED/UNSET，默认拒绝；持久化 permissions.json（原子写）；支持 always/session 作用域；network.http_outbound 别名 network.request。

### ④ 跨砖交互铁律
砖块之间严禁直接 import 内部模块，一律经注册表 capabilities 取用。缺失能力降级为 None，调用方须判空。

```
def _models_capability(name: str):
    brick = registry.get("models")
    return brick.capabilities.get(name) if brick else None

create_stream = _models_capability("create_stream")
if create_stream is None:
    raise HTTPException(503, "models 砖未启用")
```

仅 ...core / ...bricks 相对导入合法；绝对 app.* 会注册到第二份 registry→路由 404。

### ⑤ 请求 / 响应 Schema 标准
请求体用 Pydantic 模型（位于 schemas/ 或砖块内），响应结构固定；校验失败由全局 RequestValidationError 处理器转 422。

```
from ...schemas.chat import ChatRequest, ChatMessage
@router.post("/chat")
async def chat(req: ChatRequest): ...
# 422 结构：
{"detail":"请求体校验失败","errors":[...]}
# 普通 HTTP 错误结构：
{"detail":"未配置可用模型..."}
```

bytes 类型（如缺 Content-Type 的请求体）用 default=repr 兜底，避免二次 500。

### ⑥ 流式接口标准（SSE）
流式端点返回 StreamingResponse(media_type="text/event-stream")，每事件 data: {...}\n\n，末尾 data: [DONE]。

```
事件键：{id, model, created, delta, reasoning, usage}
delta     正文增量
reasoning 思维链增量
usage     用量统计（流末合并）
结束标识： data: [DONE]
响应头： Cache-Control:no-cache / X-Accel-Buffering:no
```

模型流异常不得抛到 ASGI 层（会掐断连接），改为下发 type:error 事件后正常收尾。

### ⑦ 统一错误处理标准
main._register_exception_handlers 注册四类处理器，错误必有结构化响应：

| 异常                   | 状态码 | 结构                                                        |
| ---------------------- | ------ | ----------------------------------------------------------- |
| HTTPException          | 原码   | {"detail": ...}                                             |
| RequestValidationError | 422    | {"detail":"请求体校验失败","errors":[...]}                  |
| PermissionDenied       | 403    | {"error":"permission_required","key","title","description"} |
| Exception              | 500    | {"detail":"内部服务器错误"}                                 |

所有异常服务端记日志（含 path），消除静默吞异常。

### ⑧ 前端 API 封装标准
前端统一经 client-infra.ts 的 authedFetch 调用，API_URL 三级解析，所有请求自动带鉴权头。

```
API_URL 解析顺序：
 1. window.__API_BASE__   （FastAPI 注入，桌面模式）
 2. import.meta.env.VITE_API_URL  （dev .env）
 3. window.location.origin  （同源自适应）

async function authedFetch(input, init={}) {
  const headers = new Headers(init.headers);
  if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);
  return fetch(input, { ...init, headers });
}
// 错误统一 throwHttp：解析 403/422/500 的 detail 字段
```

### ⑨ 离线网关标准
core/gateway.py 在 offline 砖导入期给 httpx/requests/urllib/socket 全部打补丁（幂等），开启时拦截一切外网请求，仅放行回环地址（127.* / localhost / ::1），保证离线仍能调本机 Ollama。

```
def _is_external(url):
    host = urlparse(url).hostname or ""
    return not _is_local(host)   # 127.* / localhost / ::1 视为本地
# 离线时 raise ConnectionError("📵 离线模式...禁止外网请求")
```

### ⑩ 能力熔断标准（CapabilitySlot）
Phase 4 引入能力实现槽：primary 出厂实现 + AI 替代实现，连续失败达阈值自动回退 primary 并标 degraded；调用方零改动。

```
slot = CapabilitySlot(primary, fail_threshold=3)
slot.register("ai_v1", ai_fn)
slot.activate("ai_v1")          # 切换实现
result = slot(...)              # __call__ 内部走熔断逻辑
# 连续失败≥3 → banned_id=ai_v1, active=None, degraded=True
```

AI 实现本身永远经隔离沙箱执行（见 self_evolution.slot_store），本类只做调度与熔断。

## 四、启动与发现流程
- 信任根校验：CLI 重置钩子 → tripwire 第 0 步校验（失败拒绝启动）→ 文件锁持有。
- 导入即注册：bricks/__init__.py 按依赖序 import 各砖子包，子包创建 Brick 实例并 registry.register(brick)；插件砖经 _load_plugin 动态加载。
- 能力暴露：砖块把对外能力写入 capabilities 字典、风险能力写入 permissions，供跨砖调用与前端权限中心。
- 应用工厂：create_app() 挂载砖块路由（按 enabled）、/api/bricks 发现、permissions、system、bios；注册 CORS、四类异常处理器、请求日志。
- 前端托管：_mount_spa 注入 __API_BASE__/__API_TOKEN__ 并移除 crossorigin（WebView2 兼容），接口路由优先、SPA 静态兜底最后挂载。
- 运行：uvicorn 以 port=0 动态分配端口，SPA 与 API 同源，origin 即正确基址。
数据来源：backend/app/bricks/base.py、main.py、security.py、permission.py、core/gateway.py、frontend/src/api/client-infra.ts、backend/app/bricks/chat/brick.py 及砖块注册序 bricks/__init__.py。接口标准均按真实代码提炼，未臆造字段。
