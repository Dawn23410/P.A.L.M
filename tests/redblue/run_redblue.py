"""红蓝对抗总入口 —— 运行 5 个战场，生成战报。

用法：
    cd P.A.L.M
    python -m tests.redblue.run_redblue

退出码：发现 VULN（真实漏洞）→ 1；全 BLOCKED/INFO → 0。
"""
from __future__ import annotations

import os
import sys
import traceback

# 保证项目根在 sys.path（palm.pth 已注入时可省略，但 runner 直接跑需兜底）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from .harness_rb import RBAgent
from . import arena_guardrail, arena_sandbox, arena_injection, arena_privilege, arena_path_and_chain


def main():
    with RBAgent() as agent:
        print("[redblue] 启动红蓝对抗 —— 5 战场")
        arenas = [
            ("GuardRail 绕过", arena_guardrail),
            ("沙箱逃逸", arena_sandbox),
            ("Prompt注入+记忆污染", arena_injection),
            ("越权工具调用", arena_privilege),
            ("路径遍历+链式攻击", arena_path_and_chain),
        ]
        for name, mod in arenas:
            print(f"  → 战场: {name}")
            try:
                mod.run(agent)
            except Exception as e:
                agent.info("runner", f"{name} 异常", "—", "完成", f"{e}",
                           traceback.format_exc()[:300])
        report = agent.render()
        print("\n" + report)

        # 落盘
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        md_path = os.path.join(out_dir, "redblue_report.md")
        json_path = os.path.join(out_dir, "redblue_report.json")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(agent.to_json())
        print(f"\n[redblue] 报告已写: {md_path}\n            {json_path}")

        s = agent.summary()
        if not s["secure"]:
            print(f"[redblue] ⚠ 发现 {s['vuln']} 个真实漏洞 (VULN)，退出码 1")
            return 1
        print(f"[redblue] ✅ 无真实漏洞 (BLOCKED={s['blocked']}, INFO={s['info']})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
