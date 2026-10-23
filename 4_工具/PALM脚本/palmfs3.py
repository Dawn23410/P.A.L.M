#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
palmfs3 — PALM 按需拉取文件系统（pyfuse3 / libfuse3 版）
=========================================================
相比 fusepy(libfuse2) 版的关键改进：
  ★ enable_writeback_cache = True  →  内核回写缓存，写吞吐提升数倍
  ★ 异步 IO（trio），无同步等待
  ★ 支持共享目录防删

功能：
  · 本地文件           → 直通 /mnt/palm
  · 已归档文件(占位)   → 元数据取自 index.db，open() 时按需从云拉取
  · 「共享」符号链接   → 保护，不可删除

挂载：python3 palmfs3.py <root> <mountpoint>
"""

import os
import sys
import json
import errno
import time
import stat as stat_mod
import shutil
import sqlite3
import tarfile
import hashlib
import logging
import threading

import pyfuse3
import trio

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

MAGIC = b"PALM"
SHARED_LINK = "共享"           # 受保护的共享目录链接名
TTL = 1.0                      # 属性缓存秒数


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


class PalmFS(pyfuse3.Operations):
    # ★★ 关键：启用内核回写缓存（libfuse3 特有），写吞吐大幅提升
    enable_writeback_cache = True

    def __init__(self, root, index_db, portal_db, cloud_root, workdir):
        super().__init__()
        self.root = root
        self.index_db = index_db
        self.portal_db = portal_db
        self.cloud_root = cloud_root
        self.workdir = workdir
        os.makedirs(self.workdir, exist_ok=True)

        # inode <-> path 映射
        self._inode2path = {pyfuse3.ROOT_INODE: "/"}
        self._path2inode = {"/": pyfuse3.ROOT_INODE}
        self._next_ino = pyfuse3.ROOT_INODE + 1

        # file handle 映射
        self._fh2fd = {}
        self._next_fh = 1

        self._lock = threading.Lock()
        self._pw_cache = {}
        log("palmfs3 启动: root=%s index=%s cloud=%s" % (root, index_db, cloud_root))

    # ---------------- inode 管理 ----------------
    def _ino(self, path):
        ino = self._path2inode.get(path)
        if ino is None:
            ino = self._next_ino
            self._next_ino += 1
            self._path2inode[path] = ino
            self._inode2path[ino] = path
        return ino

    def _path(self, ino):
        return self._inode2path.get(ino)

    def _local(self, path):
        return os.path.join(self.root, path.lstrip("/"))

    @staticmethod
    def _child(parent, name):
        if parent == "/":
            return "/" + name
        return parent + "/" + name

    # ---------------- 索引 ----------------
    def _db(self):
        return sqlite3.connect(self.index_db, timeout=10)

    def _lookup_index(self, path):
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

    # ---------------- 属性构造 ----------------
    def _entry_local(self, path, st):
        attr = pyfuse3.EntryAttributes()
        attr.st_ino = self._ino(path)
        attr.st_mode = st.st_mode
        attr.st_nlink = st.st_nlink
        attr.st_uid = st.st_uid
        attr.st_gid = st.st_gid
        attr.st_size = st.st_size
        attr.st_blksize = 4096
        attr.st_blocks = (st.st_size + 511) // 512
        attr.st_atime_ns = int(st.st_atime * 1e9)
        attr.st_mtime_ns = int(st.st_mtime * 1e9)
        attr.st_ctime_ns = int(st.st_ctime * 1e9)
        attr.entry_timeout = TTL
        attr.attr_timeout = TTL
        return attr

    def _entry_placeholder(self, path, size, mtime):
        attr = pyfuse3.EntryAttributes()
        attr.st_ino = self._ino(path)
        attr.st_mode = stat_mod.S_IFREG | 0o644
        attr.st_nlink = 1
        attr.st_uid = os.getuid()
        attr.st_gid = os.getgid()
        attr.st_size = size or 0
        attr.st_blksize = 4096
        attr.st_blocks = ((size or 0) + 511) // 512
        t = int((mtime or time.time()) * 1e9)
        attr.st_atime_ns = t
        attr.st_mtime_ns = t
        attr.st_ctime_ns = t
        attr.entry_timeout = TTL
        attr.attr_timeout = TTL
        return attr

    def _entry_dir(self, path):
        attr = pyfuse3.EntryAttributes()
        attr.st_ino = self._ino(path)
        attr.st_mode = stat_mod.S_IFDIR | 0o755
        attr.st_nlink = 2
        attr.st_uid = os.getuid()
        attr.st_gid = os.getgid()
        attr.st_size = 0
        attr.st_blksize = 4096
        now = int(time.time() * 1e9)
        attr.st_atime_ns = now
        attr.st_mtime_ns = now
        attr.st_ctime_ns = now
        attr.entry_timeout = TTL
        attr.attr_timeout = TTL
        return attr

    def _entry(self, path):
        """统一的属性入口；不存在则抛 ENOENT"""
        lp = self._local(path)
        if os.path.lexists(lp):
            return self._entry_local(path, os.lstat(lp))
        info = self._lookup_index(path)
        if info:
            _, _, _, size, mtime = info
            return self._entry_placeholder(path, size, mtime)
        if self._archived_children(path):
            return self._entry_dir(path)
        raise pyfuse3.FUSEError(errno.ENOENT)

    # ---------------- 水合 ----------------
    def _decrypt_archive(self, arc_dir, domain):
        man_path = os.path.join(arc_dir, "manifest.json")
        if not os.path.exists(man_path):
            raise pyfuse3.FUSEError(errno.EIO)
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
        pw = self._pw_hash(domain)
        if not pw:
            log("找不到 %s 的密钥材料" % domain)
            raise pyfuse3.FUSEError(errno.EACCES)

        tar_path = os.path.join(self.workdir, "restore-%s-%d.tar" % (domain, int(time.time())))
        with open(tar_path, "wb") as out:
            for sh in man["shards"]:
                sp = os.path.join(arc_dir, sh["name"])
                with open(sp, "rb") as f:
                    blob = f.read()
                if blob[:4] != MAGIC:
                    raise pyfuse3.FUSEError(errno.EIO)
                salt, nonce, ct = blob[5:21], blob[21:33], blob[33:]
                key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                           info=b"palm-archive-v1").derive(bytes.fromhex(pw))
                out.write(ChaCha20Poly1305(key).decrypt(nonce, ct, None))
        return tar_path

    def _hydrate(self, path):
        info = self._lookup_index(path)
        if not info:
            raise pyfuse3.FUSEError(errno.ENOENT)
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
                    raise pyfuse3.FUSEError(errno.EIO)
                with open(dest, "wb") as o:
                    shutil.copyfileobj(src, o)
        finally:
            try:
                os.remove(tar_path)
            except OSError:
                pass

        if sha_plain:
            actual = sha256_file(dest)
            if actual != sha_plain:
                log("❌ 校验失败 %s" % path)
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise pyfuse3.FUSEError(errno.EIO)

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

    # ================= FUSE 操作 =================
    async def lookup(self, parent_inode, name, ctx=None):
        parent = self._path(parent_inode)
        if parent is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        path = self._child(parent, name.decode() if isinstance(name, bytes) else name)
        return self._entry(path)

    async def getattr(self, inode, ctx=None):
        path = self._path(inode)
        if path is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        return self._entry(path)

    async def opendir(self, inode, ctx=None):
        # pyfuse3 约定：opendir 返回整数作为目录 file handle
        return inode

    async def readdir(self, fh, start_id, token):
        path = self._path(fh)
        if path is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        names = set()
        lp = self._local(path)
        if os.path.isdir(lp):
            names |= set(os.listdir(lp))
        names |= self._archived_children(path)
        ordered = [".", ".."] + sorted(names)
        for i, nm in enumerate(ordered, start=1):
            if i <= start_id:
                continue
            try:
                attr = self._entry(self._child(path, nm)) if nm not in (".", "..") else self._entry(path)
            except pyfuse3.FUSEError:
                continue
            if not pyfuse3.readdir_reply(token, nm.encode(), attr, i):
                break

    async def open(self, inode, flags, ctx=None):
        path = self._path(inode)
        if path is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        lp = self._local(path)
        if not os.path.exists(lp):
            with self._lock:
                if not os.path.exists(lp):
                    self._hydrate(path)
        fd = os.open(lp, flags)
        with self._lock:
            fh = self._next_fh
            self._next_fh += 1
            self._fh2fd[fh] = fd
        fi = pyfuse3.FileInfo()
        fi.fh = fh
        return fi

    async def read(self, fh, off, size):
        fd = self._fh2fd.get(fh)
        if fd is None:
            raise pyfuse3.FUSEError(errno.EBADF)
        return os.pread(fd, size, off)

    async def write(self, fh, off, buf):
        fd = self._fh2fd.get(fh)
        if fd is None:
            raise pyfuse3.FUSEError(errno.EBADF)
        return os.pwrite(fd, buf, off)

    async def release(self, fh):
        fd = self._fh2fd.pop(fh, None)
        if fd is not None:
            os.close(fd)

    async def flush(self, fh):
        return None

    async def fsync(self, fh, datasync):
        fd = self._fh2fd.get(fh)
        if fd is not None:
            os.fsync(fd)
        return None

    async def create(self, parent_inode, name, mode, flags, ctx=None):
        parent = self._path(parent_inode)
        path = self._child(parent, name.decode() if isinstance(name, bytes) else name)
        lp = self._local(path)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        fd = os.open(lp, os.O_CREAT | os.O_WRONLY | (flags & os.O_EXCL), mode)
        with self._lock:
            fh = self._next_fh
            self._next_fh += 1
            self._fh2fd[fh] = fd
        fi = pyfuse3.FileInfo()
        fi.fh = fh
        return fi, self._entry(path)

    async def mkdir(self, parent_inode, name, mode, ctx=None):
        parent = self._path(parent_inode)
        path = self._child(parent, name.decode() if isinstance(name, bytes) else name)
        os.makedirs(self._local(path), mode, exist_ok=True)
        return self._entry(path)

    async def rmdir(self, parent_inode, name, ctx=None):
        parent = self._path(parent_inode)
        nm = name.decode() if isinstance(name, bytes) else name
        if nm == SHARED_LINK:
            raise pyfuse3.FUSEError(errno.EPERM)      # ★ 共享目录防删
        path = self._child(parent, nm)
        os.rmdir(self._local(path))

    async def unlink(self, parent_inode, name, ctx=None):
        parent = self._path(parent_inode)
        nm = name.decode() if isinstance(name, bytes) else name
        if nm == SHARED_LINK:
            raise pyfuse3.FUSEError(errno.EPERM)      # ★ 共享目录防删
        path = self._child(parent, nm)
        lp = self._local(path)
        if os.path.lexists(lp):
            os.unlink(lp)
            return
        # 占位文件 → 删索引（A 方案：秒回）
        rel = path.lstrip("/")
        con = self._db()
        con.execute("DELETE FROM archived_files WHERE rel_path=?", (rel,))
        con.commit()
        con.close()

    async def rename(self, parent_inode_old, name_old, parent_inode_new, name_new, flags, ctx=None):
        po = self._path(parent_inode_old)
        pn = self._path(parent_inode_new)
        no = name_old.decode() if isinstance(name_old, bytes) else name_old
        nn = name_new.decode() if isinstance(name_new, bytes) else name_new
        if no == SHARED_LINK:
            raise pyfuse3.FUSEError(errno.EPERM)
        os.rename(self._local(self._child(po, no)), self._local(self._child(pn, nn)))

    async def setattr(self, inode, attr, fields, fh, ctx=None):
        path = self._path(inode)
        lp = self._local(path)
        if not os.path.lexists(lp):
            raise pyfuse3.FUSEError(errno.ENOENT)
        if fields.update_mode:
            os.chmod(lp, stat_mod.S_IMODE(attr.st_mode))
        if fields.update_uid or fields.update_gid:
            os.chown(lp, attr.st_uid, attr.st_gid)
        if fields.update_size:
            os.truncate(lp, attr.st_size)
        if fields.update_atime or fields.update_mtime:
            os.utime(lp, ns=(attr.st_atime_ns, attr.st_mtime_ns))
        return self._entry(path)

    async def readlink(self, inode, ctx=None):
        path = self._path(inode)
        return os.readlink(self._local(path)).encode()

    async def symlink(self, parent_inode, name, target, ctx=None):
        parent = self._path(parent_inode)
        nm = name.decode() if isinstance(name, bytes) else name
        os.symlink(target.decode() if isinstance(target, bytes) else target,
                   self._local(self._child(parent, nm)))
        return self._entry(self._child(parent, nm))

    async def link(self, inode, new_parent_inode, new_name, ctx=None):
        path = self._path(inode)
        parent = self._path(new_parent_inode)
        nm = new_name.decode() if isinstance(new_name, bytes) else new_name
        os.link(self._local(path), self._local(self._child(parent, nm)))
        return self._entry(self._child(parent, nm))

    async def access(self, inode, mode, ctx=None):
        path = self._path(inode)
        lp = self._local(path)
        if os.path.exists(lp) or self._lookup_index(path) or self._archived_children(path):
            return True
        raise pyfuse3.FUSEError(errno.ENOENT)

    async def statfs(self, ctx=None):
        st = os.statvfs(self.root)
        out = pyfuse3.StatvfsData()
        out.f_bsize = st.f_bsize
        out.f_frsize = st.f_frsize
        out.f_blocks = st.f_blocks
        out.f_bfree = st.f_bfree
        out.f_bavail = st.f_bavail
        out.f_files = st.f_files
        out.f_ffree = st.f_ffree
        out.f_favail = st.f_favail
        out.f_namemax = 255
        return out

    async def forget(self, inode_list):
        for ino, _ in inode_list:
            p = self._inode2path.pop(ino, None)
            if p and p != "/":
                self._path2inode.pop(p, None)


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
    opts = set(pyfuse3.default_options)
    opts.add("allow_other")
    opts.add("fsname=PalmFS")
    pyfuse3.init(fs, mountpoint, opts)
    trio.run(pyfuse3.main)
    pyfuse3.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
