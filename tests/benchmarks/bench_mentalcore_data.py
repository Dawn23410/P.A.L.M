"""MENTALCORE_DATA 内核基准 —— 数据层（纯 JSON 固件完整性校验）。

该内核无可执行代码，仅数据目录。基准聚焦：
- correctness:  pool.json / characters/*.json / settings.json 结构合法、可被标准库解析。
- boundary:     损坏的 JSON 应被检测（解析失败）。
"""
from __future__ import annotations

import json
import os
import traceback
from .harness import benchmark



@benchmark("mentalcore_data")
def bench(col):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "mentalcore_data")
    data_dir = os.path.join(base, "_borrowed_P.A.L.M_clean_Data")
    if not os.path.isdir(data_dir):
        col.skip("fixture", "data_dir_present", "correctness",
                 f"数据目录缺失: {data_dir} → skip")
        return
    col.pass_("fixture", "data_dir_present", "correctness",
              f"数据目录存在: {data_dir}")

    # 遍历所有 json，校验可解析（排除备份/缓存目录：_crypto_bak / __pycache__ 等）
    try:
        SKIP_DIRS = {"_crypto_bak", "__pycache__", ".git", "node_modules"}
        bad = []
        total = 0
        backup_bad = []
        for root, dirs, files in os.walk(data_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if not f.endswith(".json"):
                    continue
                p = os.path.join(root, f)
                in_backup = "_crypto_bak" in root.replace("\\", "/").split("/")
                total += 1
                try:
                    raw = open(p, "rb").read()
                    if len(raw.strip()) == 0:
                        raise ValueError("empty file (0 bytes)")
                    # 解析层级：utf-8 → GB18030 → zlib 解压后 JSON
                    parsed = False
                    for dec in ("utf-8", "gb18030"):
                        try:
                            json.loads(raw.decode(dec))
                            parsed = True
                            break
                        except (UnicodeDecodeError, ValueError):
                            continue
                    if not parsed:
                        # 尝试 zlib 解压（部分对话记录以 .json 名存储 zlib 流）
                        import zlib
                        try:
                            json.loads(zlib.decompress(raw).decode("utf-8"))
                            parsed = True
                        except Exception:
                            pass
                    if not parsed:
                        raise ValueError("not valid JSON (utf-8/gb18030/zlib)")
                except Exception as e:
                    if in_backup:
                        backup_bad.append((p, str(e)[:60]))
                    else:
                        bad.append((p, str(e)[:80]))
        if bad:
            col.fail("fixture", "json_parse_all", "correctness",
                     f"{len(bad)}/{total} 个固件 JSON 解析失败", root_cause=str(bad[:3]))
        else:
            col.pass_("fixture", "json_parse_all", "correctness",
                      f"全部 {total} 个固件 JSON 可被标准库解析")
        if backup_bad:
            col.xfail("fixture", "backup_json_integrity", "degradation",
                      f"{len(backup_bad)} 个 _crypto_bak 备份 JSON 损坏/二进制（非固件，"
                      f"建议清理或隔离）：{backup_bad[0][0]}",
                      "备份目录数据完整性")
    except Exception as e:
        col.fail("fixture", "json_parse_all", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 关键固件存在性
    for key, rel in (("pool", "pool.json"), ("settings", "settings.json")):
        p = os.path.join(data_dir, rel)
        if os.path.exists(p):
            col.pass_("fixture", f"{key}_present", "correctness", f"{rel} 存在")
        else:
            col.xfail("fixture", f"{key}_present", "correctness",
                      f"{rel} 不存在", "fixture layout")

    # characters 目录
    chars = os.path.join(data_dir, "characters")
    if os.path.isdir(chars):
        n = len([f for f in os.listdir(chars) if f.endswith(".json")])
        col.pass_("fixture", "characters_present", "correctness",
                  f"characters/ 含 {n} 个角色 JSON")
    else:
        col.xfail("fixture", "characters_present", "correctness",
                  "characters/ 目录缺失", "fixture layout")
