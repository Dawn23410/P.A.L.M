from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class SubprocessSpec:
    cmd_builder: Callable[[int], list]
    port: int = 0
    cwd: str = "."
    health_path: str = "/"
    readiness_timeout: float = 60.0
    log_path: Optional[str] = None
