"""存储池砖块的请求/响应模型（hybrid 语义化端点）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CleanupRuleModel(BaseModel):
    # 清除顺序固定 oldest_first（从老到新），此处仅暴露阈值与开关。
    order: str = "oldest_first"
    keep_min_count: int = 0
    max_age_days: float | None = None
    auto: bool = True


class CategoryCreate(BaseModel):
    name: str
    # 0 或不传表示不限容量（字节）。
    capacity_bytes: int = 0
    cleanup: CleanupRuleModel | None = None


class FileOut(BaseModel):
    id: str
    category: str
    name: str
    size: int
    stored_at: float


class CategoryOut(BaseModel):
    name: str
    capacity_bytes: int
    used_bytes: int
    count: int
    cleanup: dict


class StatsOut(BaseModel):
    total_used: int
    total_capacity: int
    total_count: int
    unlimited_categories: int
    categories: list[dict]


class ConversationLog(BaseModel):
    # 单条会话聊天记录：前端在每次变更后防抖写入后端「对话记录」分类。
    id: str
    title: str = ""
    createdAt: int = 0
    updatedAt: int = 0
    messages: list[dict] = Field(default_factory=list)
    tokenUsage: dict = Field(default_factory=dict)


class ConversationLogList(BaseModel):
    logs: list[ConversationLog] = Field(default_factory=list)
