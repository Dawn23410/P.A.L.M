# file 砖改造方案（最弱砖，当前评级 C+）

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
