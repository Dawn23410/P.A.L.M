# offline 砖修改建议

> 适用版本：P.A.L.M 砖块化架构（FastAPI + PyWebView）
> 背景：本建议在「5 个跨砖共性短板治理」中产出。短板 #4 为「offline 砖 `patch_httpx`
> 仅拦截 httpx，requests / urllib / socket 可绕过外网」。本文先说明**本轮已落实的改造**，
> 再给出**残留风险与进一步修改建议**（含路线图、兼容性、回滚）。

---

## 一、本轮已落实的改造（短板 #4 已治理）

文件：`backend/app/core/gateway.py`、`backend/app/bricks/offline/brick.py`

- `patch_httpx()` 现统一安装四条出网链路的补丁，调用方（offline 砖导入期）无感知升级：
  - `httpx`（异步客户端，原有）
  - `requests`（urllib3 适配器）
  - `urllib.request`（标准库 `OpenerDirector.open`）
  - `socket`（传输层兜底：仅放行回环地址）
- 各拦截点在拦截时经结构化日志器（`logger="offline"`）记录目标，便于审计。
- offline 砖文档同步更新，不再声明「仅 httpx 可拦」的局限。
- 判定语义：允许 `127.* / localhost / ::1 / 0.0.0.0`；其余外网（公网 IP、非回环局域网）一律拦截。
- 离线开关为进程级全局（`set_offline` 经 `POST /api/offline` 切换，导入期即安装补丁）。

验证：`backend/_smoke_gateway.py` 覆盖 httpx / requests / urllib / socket 四层拦截，
且确认「离线关闭时外网放行、离线开启时外网拦截、本机始终放行」。`TestClient` 实测
`GET /api/offline` 等只读端点鉴权也已落地（见短板 #2）。

---

## 二、残留风险（按严重度排序）

### 风险 1 · 子进程网络逃逸（高）
monkey-patch 仅作用于**当前 Python 进程**。任何由本进程 `spawn` 的子进程
（如 sandbox 引擎用 `subprocess` 启动的解释器、或 AI 代码调用 `os.system`/`subprocess`
拉起 `curl`/`wget`、或在 shell 砖里直接联网）**不会继承补丁**，其网络不受本拦截约束。

现状缓解：sandbox 引擎本身已把子进程出网指向本地拒绝代理
（`HTTP_PROXY=http://127.0.0.1:<port>`，`NO_PROXY=""`），因此沙箱内的代码外联是被兜住的。
但**非沙箱路径**拉起的子进程仍是盲区。

> 建议（最彻底）：在操作系统层做兜底——Windows 用 Windows Firewall / WFP 规则默认拒绝
> 出栈、仅放行回环；或在应用启动时统一把自身及其子进程的出网指向一个**本地拒绝代理**
> （`ALL_PROXY=http://127.0.0.1:<deny>`，`NO_PROXY=localhost,127.0.0.1`）。
> 这样无论子进程用何种客户端，出网都被 OS/代理层兜底。

### 风险 2 · 原生扩展直连（中）
C/C++ 扩展（部分 SDK）可能绕过 Python `socket` 直接 `connect`，socket 层补丁无效。
> 建议：同风险 1 的 OS 层兜底；或对高危 SDK 强制走 `httpx`/`requests` 封装，禁止裸 socket。

### 风险 3 · DNS 隐蔽通道（中）
socket 层仅检查 `connect` 的目标 IP；若进程用自定义 DNS（DoH / raw socket）或仅解析不连接，
纯应用层难以拦截。
> 建议：OS 层把 DNS 重定向到本地黑洞，仅放行本机解析器；必要时对 `socket` 的
> `AI_NUMERICHOST` 之外的解析也做审计。

### 风险 4 · 允许名单过严（低）
当前仅放行回环。若 Ollama 跑在局域网（`192.168.x.x` / `10.x.x.x`）而非本机，
离线模式会误拦本机服务，违背「离线时仍能调用 Ollama」的设计意图。
> 建议：新增 `OFFLINE_ALLOW_HOSTS` 环境变量（逗号分隔，支持域名 / CIDR / IP），
> 与 `_is_local` 合并判定（见第四节代码草图）。

### 风险 5 · 全局开关误伤合法外网功能（低）
离线开启时，任何依赖外网的写操作（如「添加模型」时 `POST /api/models/discover`
拉取供应商列表、检查更新）会直接抛 `ConnectionError`，当前错误提示较笼统。
> 建议：在捕获 `ConnectionError` 后给出中文友好提示
> 「离线模式已启用，该功能需联网，请关闭离线模式后重试」；或对明确需要外网且安全的
> 白名单域名（如模型供应商发现接口）提供 per-request 豁免。

### 风险 6 · 补丁脆弱性（低）
拦截依赖 monkey-patch 私有结构（`httpx._event_hooks`、`requests.HTTPAdapter.send`、
`urllib.request.OpenerDirector.open`），对应库大版本升级可能静默失效。
> 建议：保留 `backend/_smoke_gateway.py` 作为回归测试；并优先评估官方机制替代 monkey-patch
> （`httpx` 自定义 `Transport`、`requests` 的 `trust_env`/代理、`urllib` 自定义 `Opener`）。

---

## 三、改造路线图（建议落地优先级）

| 优先级 | 项 | 说明 |
|--------|----|------|
| **P0** | OS 层出网兜底 | 解决子进程 / 原生扩展逃逸，最彻底（风险 1/2/3） |
| **P1** | `OFFLINE_ALLOW_HOSTS` 可配置白名单 | 放行 LAN 上的 Ollama（风险 4） |
| **P1** | 离线下的友好降级提示 | 写操作捕获 `ConnectionError` 给中文说明（风险 5） |
| **P2** | 用官方机制替代 monkey-patch | 降脆弱性，保持 `smoke` 回归（风险 6） |
| **P2** | socket 层可开关 `OFFLINE_PATCH_SOCKET` | 极端冲突时的逃生阀（见第四节） |

---

## 四、建议落地的代码草图（未在本轮实现，供后续 PR 参考）

### 4.1 可配置白名单（风险 4）

```python
# backend/app/core/gateway.py
import os, ipaddress

_ALLOW_HOSTS = [h.strip() for h in os.environ.get("OFFLINE_ALLOW_HOSTS", "").split(",") if h.strip()]

def _is_allowed_extra(host: str) -> bool:
    h = host.lower().strip()
    for entry in _ALLOW_HOSTS:
        if entry.startswith(("http://", "https://")):
            entry = entry.split("://", 1)[1]
        # 精确 / 域名后缀
        if h == entry or h.endswith("." + entry):
            return True
        # CIDR
        if "/" in entry:
            try:
                if ipaddress.ip_address(h) in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                pass
    return False

# 在 _is_external 之后，各拦截点改为：
#   if _OFFLINE and _is_external(url) and not _is_allowed_extra(host): 拦截
```

### 4.2 socket 层逃生阀（风险 6 兜底）

```python
# 仅当显式关闭时才跳过 socket 层补丁
if os.environ.get("OFFLINE_PATCH_SOCKET", "1") != "0":
    _patch_socket()
```

### 4.3 写操作的友好降级（风险 5）

```python
# 在 chat / models 等需要外网的写操作处
try:
    ...  # 发起外网请求
except ConnectionError as e:
    if is_offline():
        raise HTTPException(status_code=503, detail="离线模式已启用，该功能需联网，请关闭离线模式后重试")
    raise
```

---

## 五、向后兼容与回滚

- **向后兼容**：补丁仅在离线开启时生效，联网态零行为变化；对外 API 形态不变
  （`GET/POST /api/offline`）；前端无需改动。
- **回滚**：如需回退多层拦截，仅保留 `httpx` 段（删除 `_patch_requests` / `_patch_urllib`
  / `_patch_socket` 的调用），不影响其它砖块；offline 砖仍按旧语义工作。
- **逃生阀**：若 socket 层补丁与某第三方库冲突（极少见），设 `OFFLINE_PATCH_SOCKET=0`
  关闭该层即可，其余三层照常。
- **测试**：`backend/_smoke_gateway.py` 已覆盖四层拦截与结构化日志，作为回归基线。

---

## 六、结论

本轮已把 offline 砖从「仅拦 httpx」升级为「httpx + requests + urllib + socket 四层拦截 +
结构化审计日志」，短板 #4 收敛。剩余风险集中在**进程外 / 原生扩展 / DNS 通道**，
这些无法仅靠应用层 monkey-patch 根治，需配合 **OS 层出网兜底（P0）** 与
**可配置白名单（P1）** 才能闭环。建议按第三节路线图分批落地，并以 `_smoke_gateway.py`
守护回归。
