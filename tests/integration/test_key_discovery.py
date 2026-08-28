"""TEST-0  API 密钥/后端配置文件定位（用户需求 1）。

不调用任何网络，仅确认密钥与后端配置「找得到、读得通、结构合法」。
输出定位到的文件路径（不打印密钥值）。
"""
from __future__ import annotations

import json
import os

from tests.integration.keystore import (
    find_api_key_file, load_llm_key, load_gsv_config,
)


def run(project_root: str = ".") -> dict:
    key_file = find_api_key_file()
    key, key_err = load_llm_key()
    gsv = load_gsv_config(project_root)

    checks = []
    if key_file:
        checks.append({"item": "llm_key_file", "status": "PASS",
                       "path": key_file})
    else:
        checks.append({"item": "llm_key_file", "status": "FAIL",
                       "reason": "未找到可用API 密钥文件"})

    if key:
        checks.append({"item": "llm_key_valid", "status": "PASS",
                       "provider": key.provider, "fmt": key.fmt,
                       "base_url": key.base_url,
                       "default_model": key.default_model,
                       "redacted_key": key.redacted_key,
                       "recommended_models": key.recommended_models})
    else:
        checks.append({"item": "llm_key_valid", "status": "FAIL",
                       "reason": key_err})

    if gsv.get("SOVITS_API_URL"):
        checks.append({"item": "gsv_config", "status": "PASS",
                       "url": gsv.get("SOVITS_API_URL"),
                       "port": gsv.get("SOVITS_API_PORT"),
                       "refer_wav": gsv.get("SOVITS_DEFAULT_REFER_WAV")})
    else:
        checks.append({"item": "gsv_config", "status": "SKIP",
                       "reason": "项目 .env 无 SOVITS_* 配置"})

    status = "PASS" if all(c["status"] == "PASS" for c in checks) else (
        "FAIL" if any(c["status"] == "FAIL" for c in checks) else "SKIP")
    return {"name": "key_discovery", "status": status, "checks": checks}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
