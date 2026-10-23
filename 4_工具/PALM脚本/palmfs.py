#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
palmfs — PALM 按需拉取文件系统 (FUSE)
=====================================
效果：已归档的文件在映射盘里**以正常文件名显示**，双击打开时**自动从云拉取**，
     拉取完成后成为真实本地文件（水合）。

原理：
  · 本地文件           → 直通 /mnt/palm
  · 已归档文件(占位)   → 元数据来自 index.db，getattr 返回真实 size/mtime
  · open() 命中占位    → 触发 hydrate(): 下载分片 → ChaCha20 解密 → tar 提取 → 落本地
  · 拉取成功           → 从索引移除（成为真实文件）

挂载：palmfs <root> <mountpoint> -o allow_other,default_permissions
"""

import os
import sys
import json
import errno
import time
import shutil
import sqlite3
import tarfile
import hashlib
import logging
import threading

from fuse import FUSE, Operations, FuseOSError

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

MAGIC = b"PALM"
HDR = 4 + 1 + 16 + 12          # magic + ver + salt + nonce


# ------------------------------------------------------------------ 工具
def log(msg):
    logging.info(msg)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ 主类
class PalmFS(Operations):
    def __init__(self, root, index_db, portal_db, cloud_root, workdir):
        self.root = root                  # /mnt/palm
        self.index_db = index_db          # /mnt/palm/.palm/index.db
        self.portal_db = portal_db        # /mnt/palm/.palm/portal.db
        self.cloud_root = cloud_root      # /mnt/cloudnas/tianyi/palm-archive
        self.workdir = workdir            # /var/tmp/palmfs
        os.makedirs(self.workdir, exist_ok=True)
        self._lock = threading.Lock()
        self._pw_cache = {}
        log("palmfs 启动: root=%s index=%s cloud=%s" % (root, index_db, cloud_root))

    # ---------------- 路径与索引 ----------------
    def _local(self, path):
        return os.path.join(self.root, path.lstrip("/"))

    def _db(self):
        return sqlite3.connect(self.index_db, timeout=10)

    def _lookup(self, path):
        """查索引: 返回 (domain, archive_uri, sha256_plain, size, mtime) 或 None"""
        rel = path.lstrip("/")
        if not rel:
            return None
        try:
            con = self._db()
            row = con.execute(
                "SELECT domain, archive_uri, sha256_plain, size, mtime "
                "FROM archived_files WHERE rel_path=?", (rel,)).fetchone()
            con.close()
            return row
        except sqlite3.Error as e:
            log("索引查询失败: %s" % e)
            return None

    def _archived_children(self, path):
        """某目录下的归档子项名（用于 readdir 合成）"""
        rel = path.strip("/")
        prefix = (rel + "/") if rel else ""
        out = set()
        try:
            con = self._db()
            rows = con.execute(
                "SELECT rel_path FROM archived_files WHERE rel_path LIKE ?",
                (prefix + "%",)).fetchall()
            con.close()
        except sqlite3.Error:
            return out
        for (rp,) in rows:
            rest = rp[len(prefix):]
            if rest:
                out.add(rest.split("/", 1)[0])
        return out

    def _pw_hash(self, domain):
        if domain in self._pw_cache:
            return self._pw_cache[domain]
        pw = None
        try:
            con = sqlite3.connect(self.portal_db, timeout=10)
            r = con.execute("SELECT pw FROM accounts WHERE username=?", (domain,)).fetchone()
            con.close()
            pw = r[0] if r else None
        except sqlite3.Error as e:
            log("读门户库失败: %s" % e)
        if pw:
            self._pw_cache[domain] = pw
        return pw

    # ---------------- 水合（按需拉取）----------------
    def _decrypt_archive(self, arc_dir, domain):
        """下载并解密归档目录的所有分片 → 拼回 tar 文件，返回 tar 路径"""
        man_path = os.path.join(arc_dir, "manifest.json")
        if not os.path.exists(man_path):
            raise FuseOSError(errno.EIO)
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
        pw = self._pw_hash(domain)
        if not pw:
            log("找不到 %s 的密钥材料" % domain)
            raise FuseOSError(errno.EACCES)

        tar_path = os.path.join(self.workdir, "restore-%s-%d.tar" % (domain, int(time.time())))
        with open(tar_path, "wb") as out:
            for sh in man["shards"]:
                sp = os.path.join(arc_dir, sh["name"])
                with open(sp, "rb") as f:
                    blob = f.read()
                if blob[:4] != MAGIC:
                    log("分片魔数异常: %s" % sp)
                    raise FuseOSError(errno.EIO)
                salt, nonce, ct = blob[5:21], blob[21:33], blob[33:]
                key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                           info=b"palm-archive-v1").derive(bytes.fromhex(pw))
                out.write(ChaCha20Poly1305(key).decrypt(nonce, ct, None))
        return tar_path

    def _hydrate(self, path):
        """把归档文件拉回本地"""
        info = self._lookup(path)
        if not info:
            raise FuseOSError(errno.ENOENT)
        domain, archive_uri, sha_plain, size, mtime = info
        rel = path.lstrip("/")
        log("⏳ 按需拉取: %s (域=%s, 归档=%s)" % (path, domain, archive_uri))

        arc_dir = os.path.join(self.cloud_root, archive_uri.rstrip("/"))
        tar_path = self._decrypt_archive(arc_dir, domain)
        dest = self._local(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        try:
            with tarfile.open(tar_path) as tar:
                member = tar.getmember(rel)
                src = tar.extractfile(member)
                if src is None:
                    raise FuseOSError(errno.EIO)
                with open(dest, "wb") as o:
                    shutil.copyfileobj(src, o)
        finally:
            try:
                os.remove(tar_path)
            except OSError:
                pass

        # 校验完整性
        if sha_plain:
            actual = sha256_file(dest)
            if actual != sha_plain:
                log("❌ 校验失败 %s: %s != %s" % (path, actual[:16], sha_plain[:16]))
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise FuseOSError(errno.EIO)

        # 恢复 mtime + 从索引移除（已成为真实文件）
        if mtime:
            try:
                os.utime(dest, (mtime, mtime))
            except OSError:
                pass
        try:
            con = self._db()
            con.execute("DELETE FROM archived_files WHERE rel_path=?", (rel,))
            con.commit()
            con.close()
        except sqlite3.Error:
            pass
        log("✅ 拉取完成: %s (%d 字节)" % (path, os.path.getsize(dest)))

    # ---------------- 性能优化 ----------------
    def init(self, path):
        """向内核申请更大的 IO 窗口，显著提升吞吐"""
        return {
            "max_write": 1024 * 1024,        # 单次写 1MB（默认 128KB）
            "max_readahead": 1024 * 1024,
            "max_background": 32,
            "congestion_threshold": 24,
        }

    # ---------------- FUSE 操作 ----------------
    def getattr(self, path, fh=None):
        lp = self._local(path)
        if os.path.lexists(lp):
            st = os.lstat(lp)
            return {
                "st_mode": st.st_mode,
                "st_nlink": st.st_nlink,
                "st_size": st.st_size,
                "st_atime": st.st_atime,
                "st_mtime": st.st_mtime,
                "st_ctime": st.st_ctime,
                "st_uid": st.st_uid,
                "st_gid": st.st_gid,
            }
        # 归档占位？
        info = self._lookup(path)
        if info:
            _, _, _, size, mtime = info
            now = time.time()
            return {
                "st_mode": 0o100644,       # 普通文件
                "st_nlink": 1,
                "st_size": size or 0,
                "st_atime": mtime or now,
                "st_mtime": mtime or now,
                "st_ctime": mtime or now,
                "st_uid": os.getuid(),
                "st_gid": os.getgid(),
            }
        # 归档目录？
        kids = self._archived_children(path)
        if kids:
            now = time.time()
            return {
                "st_mode": 0o040755,       # 目录
                "st_nlink": 2,
                "st_size": 0,
                "st_atime": now, "st_mtime": now, "st_ctime": now,
                "st_uid": os.getuid(), "st_gid": os.getgid(),
            }
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        names = {".", ".."}
        lp = self._local(path)
        if os.path.isdir(lp):
            names |= set(os.listdir(lp))
        names |= self._archived_children(path)
        return list(names)

    def open(self, path, flags):
        lp = self._local(path)
        if not os.path.exists(lp):
            with self._lock:
                if not os.path.exists(lp):     # 双重检查
                    self._hydrate(path)
        return os.open(lp, flags)

    def read(self, path, size, offset, fh):
        return os.pread(fh, size, offset)

    def write(self, path, data, offset, fh):
        return os.pwrite(fh, data, offset)

    def truncate(self, path, length, fh=None):
        lp = self._local(path)
        with open(lp, "r+b") as f:
            f.truncate(length)

    def create(self, path, mode, fi=None):
        lp = self._local(path)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        return os.open(lp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    def mkdir(self, path, mode):
        os.makedirs(self._local(path), mode, exist_ok=True)

    def rmdir(self, path):
        os.rmdir(self._local(path))

    def unlink(self, path):
        lp = self._local(path)
        if os.path.exists(lp):
            os.unlink(lp)
            return
        # 删占位 → 只删索引
        rel = path.lstrip("/")
        con = self._db()
        con.execute("DELETE FROM archived_files WHERE rel_path=?", (rel,))
        con.commit()
        con.close()

    def rename(self, old, new):
        os.rename(self._local(old), self._local(new))

    def chmod(self, path, mode):
        os.chmod(self._local(path), mode)

    def chown(self, path, uid, gid):
        os.chown(self._local(path), uid, gid)

    def utimens(self, path, times=None):
        os.utime(self._local(path), times)

    def release(self, path, fh):
        return os.close(fh)

    def flush(self, path, fh):
        return os.fsync(fh)

    def fsync(self, path, datasync, fh):
        return os.fsync(fh)

    def statfs(self, path):
        st = os.statvfs(self.root)
        return {
            "f_bsize": st.f_bsize, "f_frsize": st.f_frsize,
            "f_blocks": st.f_blocks, "f_bfree": st.f_bfree,
            "f_bavail": st.f_bavail, "f_files": st.f_files,
            "f_ffree": st.f_ffree, "f_favail": st.f_favail,
            "f_namemax": 255,
        }

    def readlink(self, path):
        return os.readlink(self._local(path))

    def symlink(self, target, source):
        # fusepy: symlink(target, source) —— source 是要创建的新链接
        os.symlink(target, self._local(source))

    def link(self, target, source):
        os.link(self._local(target), self._local(source))

    def access(self, path, mode):
        lp = self._local(path)
        if os.path.exists(lp):
            return 0
        if self._lookup(path) or self._archived_children(path):
            return 0
        raise FuseOSError(errno.ENOENT)


# ------------------------------------------------------------------ 入口
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    root, mountpoint = sys.argv[1], sys.argv[2]
    index_db = os.path.join(root, ".palm", "index.db")
    portal_db = os.path.join(root, ".palm", "portal.db")
    cloud_root = os.environ.get("PALM_CLOUD", "/mnt/cloudnas/tianyi/palm-archive")
    workdir = os.environ.get("PALM_WORK", "/var/tmp/palmfs")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr),
                  logging.FileHandler(os.path.join(root, ".palm", "palmfs.log"))],
    )

    fs = PalmFS(root, index_db, portal_db, cloud_root, workdir)
    FUSE(fs, mountpoint, foreground=True, allow_other=True,
         default_permissions=True, ro=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
