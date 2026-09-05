"""{name} runner

统一执行 5 个集成测试并产出报告：
  0. key_discovery   —— API 密钥/后端配置定位（用户需求 1）
  1. tts_stt_crosscheck —— TTS→STT 互相印证（用户需求 2）
  2. llm_latency     —— LLM 非网络延迟 <200ms（用户需求 3）
  3. gsv_first_token —— GSV 首字延迟 500ms-1s（用户需求 4）
  4. vosk_tailgap    —— Vosk 尾部空窗 ≤0.35s（用户需求 5）

后端未运行/依赖缺失时对应用例 SKIP（绝不伪造结果）。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from tests.integration.test_key_discovery import run as run_key
from tests.integration.test_tts_stt_crosscheck import run as run_cross
from tests.integration.test_llm_latency import run as run_llm
from tests.integration.test_gsv_first_token import run as run_gsv
from tests.integration.test_vosk_tailgap import run as run_vosk


def main():
    results = []
    results.append(run_key(_PROJECT))
    results.append(run_cross(_PROJECT))
    results.append(asyncio.run(run_llm()))
    results.append(run_gsv(_PROJECT))
    results.append(run_vosk(_PROJECT))

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    report = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "project": _PROJECT,
        "summary": counts,
        "results": results,
    }
    out_json = os.path.join(_HERE, "integration_report.json")
    out_md = os.path.join(_HERE, "integration_report.md")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = ["# P.A.L.M 集成测试报告（LLM / TTS / STT）", ""]
    lines.append(f"- 生成: {report['generated']}  Python: {report['python']}")
    lines.append(f"- 汇总: PASS={counts['PASS']} FAIL={counts['FAIL']} "
                 f"SKIP={counts['SKIP']}")
    lines.append("")
    for r in results:
        lines.append(f"## [{r['name']}] {r['status']}")
        lines.append("")
        for k, v in r.items():
            if k in ("name", "status"):
                continue
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[reports] {out_json}\n         {out_md}")
    # 退出码：仅 FAIL 返回 1（SKIP 不算失败）
    return 1 if counts["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
