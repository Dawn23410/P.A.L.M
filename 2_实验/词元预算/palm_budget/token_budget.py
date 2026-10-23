"""Token 动态预算分配器。"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


@dataclass
class Budget:
    core: int = 0
    recent: int = 0
    program: int = 0
    archived: int = 0
    system: int = 0
    conversation: int = 0


class TokenBudgetAllocator:
    def __init__(self, model_window: int = 32000):
        self._model_window = model_window
        self._consecutive_overage = 0

    @property
    def model_window(self) -> int:
        return self._model_window

    def calculate(self) -> Budget:
        w = self._model_window
        return Budget(
            core=int(w * 0.03),
            recent=int(w * 0.20),
            program=int(w * 0.01),
            archived=int(w * 0.08),
            system=int(w * 0.03),
            conversation=int(w * 0.65),
        )

    def monitor(self, conv_used: int) -> str | None:
        ratio = conv_used / self._model_window if self._model_window else 0
        if ratio > 0.85:
            self._consecutive_overage += 1
            if self._consecutive_overage >= 3:
                self._consecutive_overage = 0
                return "compress"
        else:
            self._consecutive_overage = 0
        return None

    def compress_rounds(self, rounds: int) -> int:
        return max(5, math.ceil(rounds / 5))
