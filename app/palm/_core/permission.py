from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionSpec:
    def __init__(self, key, title, description, risk=RiskLevel.LOW, brick=None):
        self.key = key
        self.title = title
        self.description = description
        self.risk = risk
        self.brick = brick


def _no_op_dependency():
    return None


def require_permission(key: str):
    # 返回依赖 callable（FastAPI Depends 语义）；独立态 no-op。
    return _no_op_dependency


def denial_message(key: str) -> str:
    return f"权限不足：{key}"


def get_engine():
    return None
