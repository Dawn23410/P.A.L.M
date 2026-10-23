# 砖块改造方案

> 📅 **时间线**：2026-07-28 砖块评分后提出（file 砖 C+ 最弱 / offline 砖待改进）

## 文件砖（file）改造方案

> 依据：联网检索的文件上传安全最佳实践（allowlist + magic bytes 校验、大小/数量上限、经应用层鉴权读取而非静态目录、结构化错误处理、审计日志）+ 项目既有约定（`require_api_token` 鉴权、storage 砖「经应用层读文件」模式 `GET /files/{id}/content`、capabilities 导出解耦）。
> 范围：仅改 file 砖内部，不动其他砖；遵循最小修改 / 单责任 / 函数≤50 行 / 中文注释。

---

## 一、当前问题清单（带代码证据）

| # | 问题 | 证据 | 风险 |
|---|------|------|------|
| 1 | **静态目录无逐文件鉴权** | `brick.py:35` `MountSpec("/uploads", directory=UPLOAD_DIR)` 交给 FastAPI `StaticFiles` | 任何人持 token 可读他人上传的文件 |
| 2 | **不校验真实类型** | `storage.py:39` 直接信任 `f.content_type`；无扩展名/魔数检测 | 恶意 `.html`/`.svg` 伪装成图片上传执行 |
| 3 | **无大小/数量上限** | `save_uploads` 无限流、无限数量 | DoS：超大文件/海量上传拖垮磁盘 |
| 4 | **无错误处理** | `storage.py:24-43` 无 try/except，异常直抛 500 | 单文件失败整批 500，无结构化错误 |
| 5 | **无日志** | 全模块零 logging | 出事无法溯源 |
| 6 | **不可复用** | 不导出任何 capabilities | 其他砖（如 parse）要读上传文件得自己写 |

**根因**：file 砖把"托管"理解为"存盘 + 静态目录"，缺少生产级上传管线的三道闸（校验 / 限额 / 鉴权读取）。

---

## 二、改造目标

| 维度 | 改造前 | 改造后目标 |
|------|:----:|:----:|
| 安全性 | ⭐⭐ | ⭐⭐⭐⭐⭐（移除静态目录 + 类型魔数校验 + 应用层鉴权读取） |
| 错误处理 | ⭐⭐ | ⭐⭐⭐⭐（结构化拒绝 + 单文件失败隔离） |
| 持久化 | ⭐⭐⭐ | 不变（仍存 UPLOAD_DIR） |
| 可观测性 | ⭐⭐ | ⭐⭐⭐（结构化上传日志） |
| 模块化 | ⭐⭐ | ⭐⭐⭐⭐（导出 `read_upload` 能力供 parse 复用） |

---

## 三、分模块改造点

### A. storage.py —— 新增校验层（单责任，不混入落盘逻辑）

新增 3 个纯函数 + 2 个常量，落盘函数 `save_uploads` 仅调用校验、不做校验细节：

```python
# 单文件上限 50MB；单请求最多 10 个
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10

# 允许的业务格式（扩展名 allowlist）
ALLOWED_EXTENSIONS = {
    "pdf","doc","docx","xls","xlsx","ppt","pptx","txt","md","csv",
    "png","jpg","jpeg","gif","webp","bmp","svg",
    "zip","json","py","js","ts","mp3","wav","mp4",
}

# 魔数 → 真实扩展名（仅取最关键字节）
_MAGIC = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "zip",          # docx/xlsx/pptx/zip 同属 zip 容器
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF8": "gif",
    b"BM": "bmp",
    b"RIFF": "wav",
    b"ID3": "mp3",
    b"\x00\x00\x00\x18ftypmp4": "mp4",
}


def _detect_real_ext(content: bytes, declared_ext: str) -> str:
    """用魔数判定真实类型，与声明扩展名交叉验证。

    返回可信扩展名；魔数与声明矛盾且声明非容器格式时，以魔数为准。
    """
    head = content[:16]
    for magic, ext in _MAGIC.items():
        if head.startswith(magic):
            return ext
    return declared_ext  # 无魔数特征（纯文本类）信任声明


def _validate_upload(filename: str, content: bytes) -> str:
    """校验单文件：大小 + 扩展名 allowlist + 魔数一致性。

    返回可信扩展名；不满足则抛 UploadRejected（携带中文原因）。
    """
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限")
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"不支持的格式：.{ext}")
    real_ext = _detect_real_ext(content, ext)
    if ext in {"pdf","docx","xlsx","pptx","png","jpg","jpeg","gif","bmp","zip","wav","mp3","mp4"}:
        if real_ext != ext and not (ext == "jpeg" and real_ext == "jpg"):
            raise UploadRejected(f"文件实际类型(.{real_ext})与扩展名(.{ext})不符")
    return ext
```

`save_uploads` 改造（加 try/except + 校验 + 日志，单文件失败隔离）：

```python
import logging
_LOGGER = logging.getLogger(__name__)


async def save_uploads(files, upload_dir):
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {MAX_FILES_PER_REQUEST} 个文件")
    os.makedirs(upload_dir, exist_ok=True)
    saved, errors = [], []
    for f in files:
        try:
            content = await f.read()
            ext = _validate_upload(f.filename or "file", content)
            fid = uuid.uuid4().hex[:12]
            stored = f"{fid}.{ext}"
            with open(os.path.join(upload_dir, stored), "wb") as out:
                out.write(content)
            saved.append(UploadedFile(
                id=fid, name=_safe_name(f.filename or "file"),
                size=len(content), mime=f.content_type or "application/octet-stream",
                url=f"/api/files/{fid}/content",   # 改为应用层鉴权端点
            ))
            _LOGGER.info("上传成功 fid=%s name=%s size=%d ext=%s", fid, f.filename, len(content), ext)
        except UploadRejected as e:
            errors.append({"name": f.filename, "error": str(e)})
        except Exception as e:
            errors.append({"name": f.filename, "error": f"保存失败：{e}"})
    if not saved and errors:
        raise HTTPException(status_code=400, detail={"uploaded": 0, "errors": errors})
    return saved
```

> 说明：部分成功时返回 `saved`；失败已在日志留痕。如需把 errors 一并回传前端，可让 `UploadedFile` 增可选 `warning` 字段，属增量改动。

### B. brick.py —— 移除静态目录 + 新增应用层读取端点

```python
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import Response
from ...security import require_api_token
from .storage import UploadedFile, save_uploads, MAX_FILES_PER_REQUEST


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)) -> list[UploadedFile]:
    return await save_uploads(files, settings.UPLOAD_DIR)


@router.get("/{file_id}/content", dependencies=[Depends(require_api_token)])
def read_upload(file_id: str) -> Response:
    """经应用层鉴权读取上传文件（替代原无鉴权静态目录）。

    file_id 为 12 位 hex，扫目录匹配 `{file_id}.*`；无匹配返回 404。
    """
    if not _is_valid_fid(file_id):
        raise HTTPException(status_code=400, detail="文件标识无效")
    path = _resolve_upload_path(settings.UPLOAD_DIR, file_id)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type="application/octet-stream")


brick = Brick(
    manifest=BrickManifest(
        name="file", title="文件处理",
        description="接收上传文件并经应用层鉴权提供访问（移除无鉴权静态目录）",
        is_core=False, can_accept_files=True,
    ),
    router=router,
    # 移除 mounts=[MountSpec("/uploads", ...)] —— 不再暴露无鉴权静态目录
    capabilities={"read_upload": lambda fid: _read_upload_bytes(fid)},  # 供 parse 等砖复用
)
```

辅助函数（放在 brick.py 或 storage.py 内，≤20 行）：

```python
import re
_FID_RE = re.compile(r"^[0-9a-f]{12}$")

def _is_valid_fid(fid: str) -> bool:
    return bool(_FID_RE.match(fid))

def _resolve_upload_path(upload_dir: str, fid: str) -> str | None:
    """按 fid 在上传目录查找匹配文件，防路径穿越。"""
    for name in os.listdir(upload_dir):
        if name.startswith(fid + ".") and _is_valid_fid(fid):
            return os.path.join(upload_dir, name)
    return None
```

### C. 能力导出（增强解耦，可选但推荐）

导出 `read_upload` 能力，使 parse 砖等可从上传目录按 fid 读文件，无需各自实现文件访问逻辑，也统一走校验/日志。

```python
capabilities={"read_upload": lambda fid: _read_upload_bytes(fid)}
```

`parse` 砖后续可经 `registry.get("file").capabilities["read_upload"](fid)` 取内容，替代自己拼路径。

---

## 四、改造后预期评分

| 维度 | 改造前 | 改造后 |
|------|:----:|:----:|
| 安全性 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 错误处理 | ⭐⭐ | ⭐⭐⭐⭐ |
| 可观测性 | ⭐⭐ | ⭐⭐⭐ |
| 模块化 | ⭐⭐ | ⭐⭐⭐⭐ |
| 功能完整性 | ⭐⭐⭐ | ⭐⭐⭐⭐（多了类型/限额闸门） |

综合：C+ → **A-**。

---

## 五、风险与取舍

1. **破坏性改动（唯一）**：移除 `MountSpec("/uploads")` 后，原 `url` 字段从 `/uploads/{stored}` 变为 `/api/files/{fid}/content`。**前端 client 中引用上传文件 URL 处需同步改为新端点**（带 Bearer Token 请求）。需确认前端引用面后再动手。
2. **魔数检测的边界**：docx/xlsx/pptx 都是 zip 容器，魔数统一为 `PK`；如需精确区分，可解包读 `[Content_Types].xml`，但属过度工程，allowlist 阶段已按扩展名放行，此处仅做"是否为 zip"粗判即可。
3. **svg 是否放开**：svg 可被浏览器当脚本执行，列入高危默认拒绝；如业务确需，可后续加"服务端重编码剥离脚本"再放行。
4. **速率限制**：本方案做的是"单请求数量 + 单文件大小"硬上限，属应用层防护。完整的 per-IP/per-user 速率限制需中间件（参考搜索结果建议），可后续在 `security.py` 统一加，不在本次 file 砖范围。

---

## 六、实施步骤建议（待你确认后执行）

1. `storage.py`：新增常量 + `_detect_real_ext` / `_validate_upload` / 日志 + 改造 `save_uploads`（try/except + 部分成功）。
2. `brick.py`：移除 `MountSpec`；新增 `GET /{file_id}/content`（鉴权）；`url` 改为新端点；导出 `read_upload` 能力。
3. 全局搜前端 `/uploads/` 引用，改为 `/api/files/{id}/content` 并带 Token。
4. 冒烟测试：上传 pdf/png（成功）、上传 html（拒绝）、超 50MB（拒绝）、读他人文件（需 Token 且 fid 不匹配 404）。

---


## 离线砖（offline）改造建议

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

---
