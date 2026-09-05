
# P.A.L.M 项目总览与产品说明（99% 补全章：宿主层澄清与前端契约实录）

> 本章为总览篇补全：澄清"宿主层"架构事实（HTTP 网关归属）、补入前端数据访问契约（api.js 实录）、并修正依赖管理表述。

---

## 补全章 A：宿主层架构事实（重大澄清）

### A.1 源码证据

1. **当前工作区 palm/ 库内无任何 FastAPI 路由定义**（全库 grep `@app.`/`APIRouter(` 零命中）。
2. `palm/services/agent/tool_base.py` 源码注释明确：*"真正的基类定义已下沉到**主板 backend/app/bricks/_shared/tooling.py**（零互导契约）"*——证明存在一个**宿主应用层（backend/app/bricks/）**，它不在当前 palm 库内。
3. 归档备份（D:/PALM_backup_20260818）中**未找到该宿主层**（bricks 仅剩 tts_sovits 与 _validation_virtual_brick；git 对象损坏无法恢复）。

### A.2 结论（修正 00/03 篇相关表述）

| 项 | 修正前（00/03 篇） | 修正后 |
|---|---|---|
| HTTP 网关 | 隐含在系统内 | **宿主层职责**（backend/app/bricks/），不在 palm 库内 |
| 163 端点 | 表述为系统现状 | 旧体系（主板时代）历史实录，非当前库内可验证 |
| API 端点清单 | 规划参考 | 明确标注：基于旧体系 routes 证据重建的宿主层规划参考 |
| 复刻 HTTP 层 | 按清单实现 | 按 **UiPort.endpoints() 契约**在宿主层自行实现路由 |

### A.3 宿主层职责（复刻者须知）

```
宿主层（backend/app/，不在 palm 库）：
  - FastAPI 路由定义（/api/chat、/api/system 等）
  - CORS/中间件
  - SSE 事件流接入
  - pywebview 桥接（window.pywebview.api）
  - 各 brick 应用装配（主板时代结构）

palm 库（纯库）：
  - 14 服务容器（build_app 装配）
  - 15 Port 契约
  - 领域/服务/适配器
  - 不持有 HTTP 层
```

---

## 补全章 B：前端数据访问契约（frontend/ui/api.js 实录）

### B.1 核心设计

```javascript
/* 数据访问封装：全前端唯一的 fetch 出口（UiPort 契约的浏览器侧）。
- BASE 由 shell 注入（同源空串 / PyWebView 桥 / 独立后端地址）。
- 所有失败统一归一为抛出 ApiError（message 中文），界面只做展示降级。
- 契约约定：后端不可达/端点缺失时界面显示「后端未连接」而非白屏。 */

export const BASE = window.PALM_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

/** 统一请求：method + path + body，超时默认 10s。 */
export async function request(method, path, body, { timeout = 10000, signal } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const resp = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: ctrl.signal,
  });
  if (!resp.ok) {
    // 解析 detail/message 作为错误信息（非 JSON 保留状态码）
    throw new ApiError(detail, resp.status);
  }
  // 空响应返回 null，否则 JSON.parse
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);
export const del = (path) => request("DELETE", path);
```

### B.2 关键事实（补全）

1. **BASE 注入**：`window.PALM_API_BASE`（同源空串 / PyWebView 桥 / 独立后端地址三态）。
2. **超时 10s**：AbortController 统一超时，错误归一"请求超时，请检查后端连接"。
3. **错误归一**：所有失败 → ApiError（中文 message）；界面显示"后端未连接"而非白屏。
4. **UiPort 契约的浏览器侧实现**：api.js 是 UiPort 的前端落点（全前端唯一 fetch 出口）。

---

## 补全章 C：依赖管理事实修正

| 项 | 修正前 | 修正后 |
|---|---|---|
| 依赖清单 | 隐含存在 | **无 requirements.txt**（仅 mentalcore/pyproject.toml） |
| 版本锁定 | 隐含 | 无版本冻结；以"能跑通验收"为准 |
| 语音依赖 | 独立 venv | venv_cosyvoice/venv_gsv 各自安装（torch cu128 等） |
| 主运行时 | venv_runtime | fastapi/uvicorn/pydantic/pyyaml/httpx 等 |

---

## 补全章 D：总览篇补全结论

**修正项汇总**：
1. 宿主层归属澄清（HTTP 网关不在 palm 库）。
2. 163 端点表述修正（旧体系实录，非当前可验证）。
3. 前端契约补入（api.js 实录：BASE 注入/10s 超时/错误归一/后端未连接提示）。
4. 依赖管理修正（无冻结清单）。

总览篇（00）此前"端点/依赖"两块缺口清零，达到 99% 完整度。
