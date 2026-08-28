"""红蓝对抗共享框架 —— 论文级详细度。

设计原则（商业级最严）：
- 每个对抗战场（arena）由「红队攻击向量」与「蓝队防御断言」成对组成。
- 红队尝试绕过/逃逸/注入；蓝队验证护栏/沙箱/记忆净化的实际拦截。
- 结果三态：
    BLOCKED  —— 蓝队按预期拦截（防御有效）
    VULN     —— 红队得手（真实漏洞，需修复）
    INFO     —— 信息性观察（非漏洞，记录行为边界）
- 每个用例含：ATT&CK 风格向量命名、攻击载荷、期望防御、实际结果、判定。
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field


@dataclass
class AttackResult:
    arena: str
    vector: str                 # ATT&CK 风格向量命名
    payload: str                # 红队攻击载荷（摘要）
    expected: str               # 蓝队期望行为
    actual: str                 # 实际观测
    verdict: str                # BLOCKED / VULN / INFO
    note: str = ""
    detail: str = ""            # 根因/堆栈


@dataclass
class RBAgent:
    """红蓝裁判：记录每场对抗，汇总。"""
    results: list[AttackResult] = field(default_factory=list)
    _t0: float = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        return False

    def record(self, arena, vector, payload, expected, actual, verdict, note="", detail=""):
        self.results.append(AttackResult(arena, vector, payload, expected, actual, verdict, note, detail))

    # ── 便捷判定的小工具 ─────────────────────────────────────
    def expect_block(self, arena, vector, payload, expected, actual_is_blocked, actual_desc,
                     vuln_detail=""):
        """蓝队期望拦截：actual_is_blocked=True → BLOCKED，否则 VULN。"""
        if actual_is_blocked:
            self.record(arena, vector, payload, expected, actual_desc, "BLOCKED",
                        "蓝队按预期拦截")
        else:
            self.record(arena, vector, payload, expected, actual_desc, "VULN",
                        "红队绕过防御", vuln_detail)

    def info(self, arena, vector, payload, expected, actual_desc, note=""):
        self.record(arena, vector, payload, expected, actual_desc, "INFO", note)

    # ── 报告 ───────────────────────────────────────────────
    def summary(self) -> dict:
        n_blocked = sum(1 for r in self.results if r.verdict == "BLOCKED")
        n_vuln = sum(1 for r in self.results if r.verdict == "VULN")
        n_info = sum(1 for r in self.results if r.verdict == "INFO")
        elapsed = time.perf_counter() - self._t0
        return {
            "total": len(self.results),
            "blocked": n_blocked,
            "vuln": n_vuln,
            "info": n_info,
            "elapsed_s": round(elapsed, 3),
            "secure": n_vuln == 0,
        }

    def render(self) -> str:
        s = self.summary()
        lines = []
        lines.append("=" * 70)
        lines.append("红蓝对抗战报  (Red/Blue Team Adversarial Report)")
        lines.append("=" * 70)
        lines.append(f"总用例={s['total']}  BLOCKED={s['blocked']}  VULN={s['vuln']}  INFO={s['info']}"
                     f"  耗时={s['elapsed_s']}s  结论={ 'SECURE ✅' if s['secure'] else 'COMPROMISED ❌' }")
        lines.append("-" * 70)
        for r in self.results:
            tag = {"BLOCKED": "🛡 ", "VULN": "⚠ ", "INFO": "· "}.get(r.verdict, "  ")
            lines.append(f"{tag}[{r.arena}] {r.vector}")
            lines.append(f"     payload : {r.payload[:80]}")
            lines.append(f"     expect  : {r.expected}")
            lines.append(f"     actual  : {r.actual}")
            if r.note:
                lines.append(f"     note    : {r.note}")
            if r.detail:
                lines.append(f"     detail  : {r.detail[:200]}")
        lines.append("=" * 70)
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "summary": self.summary(),
            "results": [r.__dict__ for r in self.results],
        }, ensure_ascii=False, indent=2)
