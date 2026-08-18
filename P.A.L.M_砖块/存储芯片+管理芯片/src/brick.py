"""storage 砖块：文件统一分类存储。

四个语义化端点组，对应需求：
- 分类存储：  POST /api/storage/files
- 分类管理：  GET/POST/DELETE /api/storage/categories
- 容量统计：  GET  /api/storage/stats
- 自适应清除：POST /api/storage/categories/{name}/cleanup（上传超限也会自动触发）
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Body, Depends, File, HTTPException, Response, UploadFile

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from .breakdown import get_breakdown

logger = get_logger(__name__)
from .pool import (
    category_view,
    cleanup_category,
    compute_stats,
    decrypt_all_encrypted_gen,
    delete_category,
    delete_file,
    encrypt_all_plaintext_gen,
    index_existing_file,
    encryption_summary,
    find_config_file,
    load_config_json,
    read_file_content,
    safe_category,
    save_config_json,
    store_file,
)
from .redundancy import vault as _redundancy_vault
from .redundancy.recycle import send_to_recycle_bin as _recycle_fn
from .controller.quota import (
    StorageQuotaError,
    get_storage_quota,
    reserve_bytes,
    set_category_quota,
    set_global_quota,
)
from .controller.lifecycle import (
    apply_cleanup_policy,
    archive_file_to_vault,
    set_category_tier,
    set_tier_policy,
)
from .controller.audit import list_storage_events
from .controller.health import storage_health
from .schemas import CategoryCreate, CategoryOut, FileOut, StatsOut
from .state import CategoryMeta, CleanupRule, PoolStore

router = APIRouter(prefix="/api/storage", tags=["storage"])

# 全局单例：元信息与磁盘文件都由它统一管理。
store = PoolStore(fallback_dir(settings.STORAGE_POOL_DIR, __file__))

# 应用设置以固定文件名持久化在「配置文件」分类下，作为 JSON 文件存储。
SETTINGS_CATEGORY = "配置文件"
SETTINGS_FILENAME = "settings.json"


@router.post("/categories", response_model=CategoryOut, dependencies=[Depends(require_api_token)])
def create_category(body: CategoryCreate) -> CategoryOut:
    name = safe_category(body.name)
    if not name:
        raise HTTPException(status_code=400, detail="分类名无效")
    rule = body.cleanup
    cleanup = CleanupRule(
        order=rule.order if rule else "oldest_first",
        keep_min_count=rule.keep_min_count if rule else 0,
        max_age_days=rule.max_age_days if rule else None,
        auto=rule.auto if rule else True,
    ) if rule else CleanupRule()
    with store.transaction() as state:
        # 建分类或覆盖容量/规则（已存在则更新治理参数）。
        state.categories[name] = CategoryMeta(
            name=name,
            capacity_bytes=max(0, int(body.capacity_bytes)),
            cleanup=cleanup,
            created_at=state.categories.get(name, CategoryMeta(name=name)).created_at
            or time.time(),
        )
        view = category_view(state, name)
    logger.info("创建分类 name=%s", name)
    return CategoryOut(**view)


@router.get("/categories", response_model=list[CategoryOut], dependencies=[Depends(require_api_token)])
def list_categories() -> list[CategoryOut]:
    # 只读：避免 GET 端点触发落盘导致 Windows 下 PermissionError。
    state = store.get_state()
    return [CategoryOut(**category_view(state, n)) for n in state.categories]


@router.delete("/categories/{name}", dependencies=[Depends(require_api_token), Depends(require_permission("storage.delete"))])
def remove_category(name: str) -> dict:
    ok = delete_category(store, safe_category(name))
    if not ok:
        raise HTTPException(status_code=404, detail="分类不存在")
    logger.warning("删除分类 name=%s", name)
    return {"deleted": True}


@router.post("/files", response_model=list[FileOut], dependencies=[Depends(require_api_token)])
async def upload_to_category(files: list[UploadFile] = File(...), category: str = "") -> list[FileOut]:
    cat = safe_category(category)
    if not cat:
        raise HTTPException(status_code=400, detail="分类名无效")
    saved: list[FileOut] = []
    for f in files:
        content = await f.read()
        record = store_file(store, cat, f.filename or "file", content)
        saved.append(FileOut(**record.to_dict()))
    return saved


@router.get("/files", response_model=list[FileOut], dependencies=[Depends(require_api_token)])
def list_files(category: str = "") -> list[FileOut]:
    # 只读：避免 GET 端点触发落盘导致 Windows 下 PermissionError。
    cat = safe_category(category) if category else ""
    state = store.get_state()
    files = state.files
    if cat:
        files = [x for x in files if x.category == cat]
    files = sorted(files, key=lambda f: f.stored_at, reverse=True)
    return [FileOut(**f.to_dict()) for f in files]


@router.delete("/files/{file_id}", dependencies=[Depends(require_api_token), Depends(require_permission("storage.delete"))])
def remove_file(file_id: str) -> dict:
    ok = delete_file(store, file_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文件不存在")
    logger.warning("删除文件 file_id=%s", file_id)
    return {"deleted": True}


@router.get("/stats", response_model=StatsOut, dependencies=[Depends(require_api_token)])
def stats() -> StatsOut:
    return StatsOut(**compute_stats(store))


@router.get("/breakdown", dependencies=[Depends(require_api_token)])
def breakdown() -> dict:
    # 存储池各分类的实际占用占比（容量上限之和 / 已用 / 未用空间）。
    return get_breakdown()


@router.get("/quota", dependencies=[Depends(require_api_token)])
def quota() -> dict:
    # 配额总览：已用 / 限额 / 各分类占用（只读）。
    return get_storage_quota(store)


@router.put("/quota", dependencies=[Depends(require_api_token), Depends(require_permission("storage.quota"))])
def set_quota(body: dict = Body(default={})) -> dict:
    # 设置总字节配额（quota_bytes，0=不限）。
    return set_global_quota(store, int(body.get("quota_bytes", 0)))


@router.put("/categories/{name}/quota", dependencies=[Depends(require_api_token), Depends(require_permission("storage.quota"))])
def set_cat_quota(name: str, body: dict = Body(default={})) -> dict:
    # 设置分类级字节上限；分类不存在返回 404。
    result = set_category_quota(store, safe_category(name), int(body.get("capacity_bytes", 0)))
    if result is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    return result


@router.get("/encryption", dependencies=[Depends(require_api_token)])
def encryption_status() -> dict:
    # 检测存储池文件加密状态：available=加密能力可用，all_encrypted=全部文件均已加密。
    return encryption_summary(store)



@router.get("/files/{file_id}/content", dependencies=[Depends(require_api_token)])
def read_file(file_id: str) -> Response:
    # 返回文件明文内容（加密文件经 crypto 能力还原）；无法读取或解密则 404。
    data = read_file_content(store, file_id)
    if data is None:
        raise HTTPException(status_code=404, detail="文件不存在或无法解密")
    return Response(content=data, media_type="application/octet-stream")


@router.post("/categories/{name}/cleanup", response_model=list[FileOut], dependencies=[Depends(require_api_token), Depends(require_permission("storage.prune"))])
def trigger_cleanup(name: str) -> list[FileOut]:
    # 生命周期引擎：容量/年龄清理 + 冷层归档联动（替代原 cleanup_category）。
    cat = safe_category(name)
    with store.transaction() as state:
        if cat not in state.categories:
            raise HTTPException(status_code=404, detail="分类不存在")
    removed = apply_cleanup_policy(store, cat)
    logger.warning("清理分类 name=%s removed=%d", cat, len(removed))
    return [FileOut(**f.to_dict()) for f in removed]


@router.put("/tiers/{tier}", dependencies=[Depends(require_api_token), Depends(require_permission("storage.quota"))])
def put_tier_policy(tier: str, body: dict = Body(default={})) -> dict:
    # 设置冷热分层默认策略（keep_max_bytes / auto_clean）。
    return set_tier_policy(store, tier, int(body.get("keep_max_bytes", 0)), bool(body.get("auto_clean", False)))


@router.post("/categories/{name}/tier", dependencies=[Depends(require_api_token), Depends(require_permission("storage.quota"))])
def post_category_tier(name: str, body: dict = Body(default={})) -> dict:
    # 把整个分类标记为某分层（如日志分类整体设为 cold 归档）。
    ok = set_category_tier(store, safe_category(name), str(body.get("tier", "hot")))
    if not ok:
        raise HTTPException(status_code=404, detail="分类不存在")
    return {"ok": True, "tier": body.get("tier", "hot")}


@router.post("/files/{file_id}/archive", dependencies=[Depends(require_api_token), Depends(require_permission("storage.prune"))])
def archive_file(file_id: str) -> dict:
    # 手动把文件归档到保险库（保留索引，仅留副本兜底）。
    result = archive_file_to_vault(store, file_id)
    if not result.get("ok") and "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.get("/events", dependencies=[Depends(require_api_token)])
def storage_events(limit: int = 100) -> list:
    # 审计事件（倒序，最新在前）。
    return list_storage_events(store, limit)


@router.get("/health", dependencies=[Depends(require_api_token)])
def storage_health_view() -> dict:
    # 健康监测（SMART 隐喻）：容量/剩余/加密覆盖/碎片率/配额/最近异常。
    return storage_health(store)


brick = Brick(
    manifest=BrickManifest(
        name="storage",
        title="存储芯片+管理芯片",
        description="主板自带存储组件：介质层（块读写/加密/压缩/索引）+ 管理芯片（配额/冷热分层/审计/冗余保险库/健康监测）",
        bus_type="chip",
    ),
    router=router,
    capabilities={
        # 经 capabilities 暴露给 crypto 砖消费，供其「全量加/解密存量」时调用，不跨砖 import。
        "encrypt_all_plaintext": lambda: encrypt_all_plaintext_gen(store),
        "decrypt_all_encrypted": lambda: decrypt_all_encrypted_gen(store),
        # 暴露应用设置读取，供 settings/llm 砖在不跨砖 import 的前提下获取 Token 配额等配置。
        "load_app_settings": lambda: load_config_json(store, SETTINGS_CATEGORY, SETTINGS_FILENAME) or {},
        # 暴露存储原语，供 conversations 砖复用单例落盘（含 crypto 加密与 pool.json 索引），不跨砖 import。
        "get_store": lambda: store,
        "store_file": lambda *a, **k: store_file(store, *a, **k),
        "read_file_content": lambda *a, **k: read_file_content(store, *a, **k),
        "find_config_file": lambda *a, **k: find_config_file(store, *a, **k),
        "delete_file": lambda *a, **k: delete_file(store, *a, **k),
        # 暴露「登记已存在磁盘文件」原语，供 agent 工具把直写产物纳入索引（A1 前置）。
        "index_existing_file": lambda *a, **k: index_existing_file(store, *a, **k),
        # ── 管理芯片·冗余层（M0 自 sandbox 迁入，行为不变仅移动）──
        # vault 模块（删除前归档 + 检索恢复），供 safety/brick 与 bios 自检消费。
        "vault": lambda: _redundancy_vault,
        # 删除路由回收站（先归档保险库再移回收站），供 agent 文件工具消费。
        "recycle_bin": lambda: _recycle_fn,
        "send_to_recycle_bin": lambda: _recycle_fn,  # 兼容别名
        # 细粒度冗余能力（供 M4 端点与消费方按需取用）。
        "archive_before_delete": lambda: _redundancy_vault.archive_before_delete,
        "restore_from_vault": lambda: _redundancy_vault.restore_from_vault,
        "list_vault": lambda: _redundancy_vault.list_vault(),
        "get_vault_stats": lambda: _redundancy_vault.get_vault_stats(),
        "resolve_vault_root": lambda: _redundancy_vault.resolve_vault_root(),
        "delete_vault_entry": lambda: _redundancy_vault.delete_vault_entry,
        "clear_vault": lambda: _redundancy_vault.clear_vault,
        # ── 管理芯片·配额（M2 字节配额，对标 token 配额）──
        "get_storage_quota": lambda: get_storage_quota(store),
        "reserve_bytes": lambda *a, **k: reserve_bytes(store, *a, **k),
        "set_category_quota": lambda *a, **k: set_category_quota(store, *a, **k),
        "set_global_quota": lambda *a, **k: set_global_quota(store, *a, **k),
        # ── 管理芯片·生命周期（M3 冷热分层 + vault 归档联动）──
        "apply_cleanup_policy": lambda *a, **k: apply_cleanup_policy(store, *a, **k),
        "set_tier_policy": lambda *a, **k: set_tier_policy(store, *a, **k),
        "set_category_tier": lambda *a, **k: set_category_tier(store, *a, **k),
        "archive_file_to_vault": lambda *a, **k: archive_file_to_vault(store, *a, **k),
        # ── 管理芯片·审计与健康（M4）──
        "list_storage_events": lambda *a, **k: list_storage_events(store, *a, **k),
        "storage_health": lambda: storage_health(store),
    },
    permissions=[
        PermissionSpec(key="storage.delete", title="删除存储文件/分类",
                        description="永久删除存储池中的文件或整个分类，不可恢复。",
                        risk=RiskLevel.HIGH, brick="storage"),
        PermissionSpec(key="storage.prune", title="清理存储分类",
                        description="按容量规则自动或手动清除分类内的旧文件。",
                        risk=RiskLevel.MEDIUM, brick="storage"),
        PermissionSpec(key="storage.quota", title="调整存储配额",
                        description="设置存储池总字节配额或分类级容量上限。",
                        risk=RiskLevel.MEDIUM, brick="storage"),
    ],
)
registry.register(brick)