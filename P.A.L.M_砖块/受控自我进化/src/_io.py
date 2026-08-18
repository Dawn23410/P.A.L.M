"""原子写 JSON 与目录安全准备（复用 settings 砖 _atomic_write_json 思路）。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time

_LOGGER = logging.getLogger(__name__)


def atomic_write_json(path: str, data: dict, max_retries: int = 6) -> None:
    """同目录唯一临时文件 + os.replace 重试，规避 Windows 并发写/杀软共享冲突。

    固定名临时文件在并发场景会触发 WinError 32 / Errno 13，故用 mkstemp 生成唯一名。
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    last_err: OSError | None = None
    for attempt in range(max_retries):
        try:
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            os.replace(tmp, path)
            return
        except (PermissionError, OSError) as err:
            last_err = err
            try:
                os.unlink(tmp)
            except OSError as exc:
                _LOGGER.debug("临时文件清理失败（重试中）: %s", exc)
            time.sleep(0.05 * (attempt + 1))
    raise last_err or RuntimeError("原子写失败")
