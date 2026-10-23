"""palm_cryptokernel._private_fs 测试：最小权限落盘 + 缓存**不削弱**安全。

重点不只是"权限收紧能生效"，更是"缓存不会漏收紧"：Windows 上 `icacls` 是子进程
（实测 ≈15–22ms/次），本模块靠缓存把它从"每次写一次"降为"每对象一次"；一旦缓存
判断写错，就会变成"以为收紧了、实际裸奔"——安全模块里这比没收紧更危险，
所以下面有专门的证伪用例（文件被删后重建、目录收紧失败、显式调用不走缓存）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import _private_fs  # noqa: E402

_WIN = os.name == "nt"


def _icacls(path: str) -> str:
    """读取路径 ACL 原文（本地化输出可能非 UTF-8，用 replace 兜底；ASCII 账户名不受影响）。"""
    proc = subprocess.run(["icacls", path], capture_output=True, timeout=10,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc.stdout.decode("utf-8", errors="replace")


class _CountingAcl:
    """把 icacls 换成可计数的假实现，用来观察"到底调了几次子进程"。"""

    def __init__(self, result: bool = True):
        self.calls: list[str] = []
        self.result = result

    def __call__(self, path: str, inherit_children: bool = False) -> bool:
        self.calls.append(path)
        return self.result

    @property
    def n(self) -> int:
        return len(self.calls)


class HardenCacheTest(unittest.TestCase):
    """缓存语义（Windows ACL 路径；POSIX 走 chmod，不进这套缓存）。"""

    def setUp(self):
        _private_fs.reset_harden_cache()
        self.tmp = tempfile.mkdtemp(prefix="palm_pfs_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _patch(self, result: bool = True):
        fake = _CountingAcl(result)
        patcher = mock.patch.object(_private_fs, "_windows_acl", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_first_write_hardens_then_hits_cache(self):
        acl = self._patch()
        p = os.path.join(self.tmp, "k.bin")
        self.assertTrue(_private_fs.write_private_bytes(p, b"a"))
        self.assertEqual(acl.n, 1)
        _private_fs.write_private_bytes(p, b"bb")
        self.assertEqual(acl.n, 1, "同一文件的重复写不应再起 icacls 子进程")

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_new_file_in_managed_dir_inherits_without_acl(self):
        acl = self._patch()
        d = os.path.join(self.tmp, "keys")
        self.assertTrue(_private_fs.ensure_dir(d))
        self.assertEqual(acl.n, 1, "目录收紧一次")
        _private_fs.write_private_bytes(os.path.join(d, "a.bin"), b"a")
        _private_fs.write_private_bytes(os.path.join(d, "b.bin"), b"b")
        self.assertEqual(acl.n, 1, "自管目录内的新建文件靠继承，不该再逐个收紧")

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_deleted_and_recreated_file_is_hardened_again(self):
        """🔴 关键：缓存存的是"文件身份"，删掉重建必须重新收紧，否则就是裸奔。"""
        acl = self._patch()
        p = os.path.join(self.tmp, "gone.bin")
        _private_fs.write_private_bytes(p, b"a")
        self.assertEqual(acl.n, 1)
        os.remove(p)
        _private_fs.write_private_bytes(p, b"a")
        self.assertEqual(acl.n, 2, "换了文件对象就必须重新收紧")

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_explicit_restrict_never_cached(self):
        acl = self._patch()
        p = os.path.join(self.tmp, "x.bin")
        _private_fs.write_private_bytes(p, b"a")
        _private_fs.restrict_file(p)
        _private_fs.restrict_file(p)
        self.assertEqual(acl.n, 3, "显式 restrict 是「现在就做」，必须真执行")

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_failure_is_reported_and_not_cached(self):
        acl = self._patch(result=False)
        p = os.path.join(self.tmp, "f.bin")
        self.assertFalse(_private_fs.write_private_bytes(p, b"a"), "失败必须如实返回 False")
        self.assertEqual(acl.n, 1)
        _private_fs.write_private_bytes(p, b"a")
        self.assertEqual(acl.n, 2, "失败不写缓存，下次仍要重试")

    @unittest.skipUnless(_WIN, "仅 Windows 有 icacls 路径")
    def test_managed_dir_failure_blocks_inherit_shortcut(self):
        """目录收紧失败 ⇒ 不能登记为自管目录 ⇒ 子文件仍要自己收紧。"""
        acl = self._patch(result=False)
        d = os.path.join(self.tmp, "keys2")
        self.assertFalse(_private_fs.ensure_dir(d))
        self.assertFalse(_private_fs.write_private_bytes(os.path.join(d, "a.bin"), b"a"))
        self.assertEqual(acl.n, 2)

    def test_cache_stats_and_reset(self):
        _private_fs.write_private_text(os.path.join(self.tmp, "a.bin"), "a")
        self.assertEqual(_private_fs.harden_cache_stats()["files"], 1)
        _private_fs.reset_harden_cache()
        self.assertEqual(_private_fs.harden_cache_stats(), {"dirs": 0, "files": 0})


class RealAclTest(unittest.TestCase):
    """真机验证：跳过 icacls 的文件**确实**继承到了受限 ACL（不是"以为收紧了"）。"""

    def setUp(self):
        _private_fs.reset_harden_cache()
        if not _WIN:
            self.skipTest("仅 Windows")
        self.tmp = tempfile.mkdtemp(prefix="palm_pfs_real_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _assert_excludes_common_users(self, path: str):
        out = _icacls(path)
        self.assertNotIn("Everyone", out, f"仍含 Everyone:\n{out}")
        self.assertNotIn("BUILTIN\\Users", out, f"仍含 BUILTIN\\Users:\n{out}")
        self.assertIn(os.environ.get("USERNAME", "?"), out)

    def test_file_hardened_by_icacls(self):
        p = os.path.join(self.tmp, "direct.bin")
        if not _private_fs.write_private_bytes(p, b"x"):
            self.skipTest("本机 icacls 不可用（已如实返回 False）")
        self._assert_excludes_common_users(p)

    def test_inherited_acl_covers_new_file(self):
        """目录带 (OI)(CI) 后，新建文件不调 icacls 也应已受限 —— 这条是本次提速的前提。"""
        d = os.path.join(self.tmp, "keys")
        if not _private_fs.ensure_dir(d):
            self.skipTest("本机 icacls 不可用（已如实返回 False）")
        p = os.path.join(d, "inherited.bin")
        self.assertTrue(_private_fs.write_private_bytes(p, b"y"))
        self._assert_excludes_common_users(p)


class ContentContractTest(unittest.TestCase):
    """落盘内容/权限的接口契约（跨平台）。"""

    def setUp(self):
        _private_fs.reset_harden_cache()
        self.tmp = tempfile.mkdtemp(prefix="palm_pfs_io_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_write_bytes_round_trip(self):
        p = os.path.join(self.tmp, "b.bin")
        raw = bytes(range(256)) * 4
        _private_fs.write_private_bytes(p, raw)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), raw)
        _private_fs.write_private_bytes(p, b"short")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"short", "应截断重写")

    def test_write_text_is_utf8(self):
        p = os.path.join(self.tmp, "t.txt")
        _private_fs.write_private_text(p, "猫娘：密钥🔑")
        with open(p, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "猫娘：密钥🔑")

    @unittest.skipUnless(os.name == "posix", "POSIX 才有 mode 语义")
    def test_posix_modes(self):
        d = os.path.join(self.tmp, "keys")
        self.assertTrue(_private_fs.ensure_dir(d))
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        p = os.path.join(d, "k.bin")
        _private_fs.write_private_bytes(p, b"x")
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_restrict_if_exists_tolerates_missing(self):
        self.assertTrue(_private_fs.restrict_if_exists(os.path.join(self.tmp, "nope")))


if __name__ == "__main__":
    unittest.main()
