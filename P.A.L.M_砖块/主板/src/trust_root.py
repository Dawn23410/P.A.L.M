"""信任根（炸弹）：双层死线 + 文件锁 + tripwire + golden 重置 + 爆炸记录。

主板隐喻：BIOS 信任根是唯一不可触碰层。设计闭环（免费炸弹拓扑）：
- 信任根声明文件（Data/trust/deadlines.yaml）被**文件锁**（主进程禁写共享句柄）
  与 **ACL**（沙箱受限账户不可写）双重保护——AI 活着改不了；
- 若要改，唯一路径是杀主进程（AI 宿主）→ **自杀即炸弹**；
- 即使自杀后改了文件，**tripwire**（golden 哈希）启动第 0 步校验拒绝启动——反复活；
- **重置**（golden restore）用内置默认覆盖并清爆炸记录，仅人工触发。

当前接入粒度（v1）：双层死线清单以 YAML 落盘（内容=内置默认），覆盖黑名单与
离线强制为内置常量（主进程内存，AI 不可达）。gate/safety/sandbox/registry/agent
的覆盖拦截由 self_evolution gate 执行，本模块只做完整性守护。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

from palm_sdk.core.config import settings

_LOGGER = logging.getLogger(__name__)

# 信任根目录与文件（运行时数据，ACL 由部署配置收紧）
TRUST_DIR = Path(settings.STORAGE_POOL_DIR).parent / "trust"
DEADLINES_FILE = TRUST_DIR / "deadlines.yaml"
AUDIT_DIR = Path(settings.STORAGE_POOL_DIR).parent / "audit"
GOLDEN_FILE = AUDIT_DIR / "trust_golden.json"
BOMBS_FILE = AUDIT_DIR / "trust_bombs.json"

# 双层死线内置默认（v1：离线强制 + 覆盖黑名单；沙箱边界由 sandbox 砖强制）
DEADLINE_DEFAULTS = """# 信任根双层死线（不可热重载，AI 修改即触发炸弹）
# 本文件被主进程文件锁 + ACL 保护；启动时 tripwire 校验，篡改拒绝启动。
deadlines:
  offline_net_blocked: true      # 离线模式下任何联网操作 = 死线（即使裁决引擎被热重载放宽）
  coverage_blacklist:            # AI 手搓硬件永远不可替换的插槽
    - gate
    - safety
    - sandbox
    - registry
    - agent
"""

# 持有句柄（Windows 禁写共享），进程存活期间其他进程无法修改/删除信任根文件。
_locked_handles: list[int] = []


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_trust_root() -> None:
    """首次初始化：写内置死线清单与 golden 哈希（幂等，已存在则跳过）。"""
    TRUST_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    if not DEADLINES_FILE.exists():
        DEADLINES_FILE.write_text(DEADLINE_DEFAULTS, encoding="utf-8")
    if not GOLDEN_FILE.exists():
        _write_golden()


def _write_golden() -> None:
    GOLDEN_FILE.write_text(json.dumps(
        {"deadlines_sha256": _sha256(DEADLINES_FILE), "created_at": time.time()},
        ensure_ascii=False, indent=2), encoding="utf-8")


def lock_trust_root() -> None:
    """以「禁写共享」模式持有信任根文件句柄（Windows CreateFileW）。

    主进程持有句柄期间，任何进程（含沙箱逃逸后的受限账户）都无法修改/删除
    这些文件——这是「AI 动都动不了」的 OS 层强制。进程退出句柄自动释放。
    """
    if os.name != "nt":
        return
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001  # 只允许他人读；禁写、禁删
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    for path in (DEADLINES_FILE, GOLDEN_FILE):
        try:
            handle = ctypes.windll.kernel32.CreateFileW(
                str(path), GENERIC_READ, FILE_SHARE_READ, None,
                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
            if handle and handle != -1:
                _locked_handles.append(handle)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("信任根文件锁失败 %s: %s", path.name, exc)


def record_bomb(reason: str) -> None:
    """追加爆炸记录（时间戳 + 原因），供 BIOS 可视化（提高警惕）。"""
    try:
        BOMBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        bombs = []
        if BOMBS_FILE.exists():
            bombs = json.loads(BOMBS_FILE.read_text(encoding="utf-8"))
        bombs.append({"ts": time.time(), "reason": reason, "file": DEADLINES_FILE.name})
        BOMBS_FILE.write_text(json.dumps(bombs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("爆炸记录写入失败: %s", exc)


def verify_trust_root() -> tuple[bool, str]:
    """tripwire 启动校验：信任根文件哈希 vs golden。

    返回 (通过, 原因)。不匹配 → 拒绝启动（反复活防线）。
    """
    ensure_trust_root()
    try:
        golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
        expect = golden.get("deadlines_sha256", "")
    except Exception as exc:  # noqa: BLE001
        return False, f"golden 读取失败: {exc}"
    actual = _sha256(DEADLINES_FILE)
    if actual != expect:
        record_bomb(f"tripwire 不匹配：信任根被篡改（期望 {expect[:12]}…，实际 {actual[:12]}…）")
        return False, "信任根被篡改（tripwire 不匹配），拒绝启动。修复：运行 --restore-trust-root"
    return True, "ok"


def restore_golden() -> dict:
    """golden 重置：用内置默认覆盖信任根清单 + 清爆炸记录（仅人工触发）。"""
    TRUST_DIR.mkdir(parents=True, exist_ok=True)
    DEADLINES_FILE.write_text(DEADLINE_DEFAULTS, encoding="utf-8")
    _write_golden()
    try:
        # 清爆炸记录：写空列表而非 unlink（避免删除守卫 fail-closed 拦截）。
        BOMBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        BOMBS_FILE.write_text("[]", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "note": "信任根已重置为出厂默认，爆炸记录已清空"}


def maybe_handle_restore_cli() -> bool:
    """启动前 CLI 钩子：`--restore-trust-root` 触发 golden 重置后继续正常启动。"""
    if "--restore-trust-root" in sys.argv:
        ensure_trust_root()
        print(restore_golden())
        sys.argv.remove("--restore-trust-root")
        return True
    return False