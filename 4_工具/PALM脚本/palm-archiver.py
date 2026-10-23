#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
palm-archiver — PALM 冷数据加密归档引擎（运行于 PVE 宿主）
==========================================================
触发条件 : HDD(/mnt/wd500) 使用率 >= 80%
归档流程 :
  1. 遍历各账号可见域 (public + private/<账号>)
  2. 收集「小于 50MB 的碎片文件」
  3. tar 打包 → split 切成 500MB 分片
  4. ChaCha20-Poly1305 + 随机盐 加密（密钥按门户账号派生）
  5. 生成 sha256 校验清单 manifest.json
  6. 上传到天翼云盘（CD2 挂载点 /mnt/cloudnas/tianyi）
  7. 删除本地真实文件 → 留下 .palmcloud 占位 → 写入 SQLite 文件表

用法 :
  python3 palm-archiver.py                # 正常（受 80% 阈值约束）
  python3 palm-archiver.py --force        # 强制归档（测试用）
  python3 palm-archiver.py --dry-run      # 只扫描统计，不动文件
  python3 palm-archiver.py --list         # 打印文件表
"""

import os
import sys
import json
import time
import sqlite3
import hashlib
import tarfile
import argparse
import subprocess
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# ------------------------------------------------------------------ 配置
HDD_MONITOR = "/mnt/wd500"                        # 监控使用率的目标
SRC_ROOT    = "/mnt/palm"                         # 归档源（4TB vdisk）
DST_ROOT    = "/mnt/cloudnas/tianyi/palm-archive" # 天翼云盘归档根（CD2 挂载）
INDEX_DIR   = "/mnt/palm/.palm"                   # 索引/日志目录
INDEX_DB    = os.path.join(INDEX_DIR, "index.db")
LOG_FILE    = os.path.join(INDEX_DIR, "archiver.log")
PORTAL_DB   = "/tmp/palm-portal.db"               # 从 CT103 导出的门户库副本
THRESHOLD   = 80                                  # 触发阈值 %
FRAG_MAX    = 50 * 1024 * 1024                    # 碎片阈值 50MB
SHARD_SIZE  = 500 * 1024 * 1024                   # 分片大小 500MB
STUB_SUFFIX = ".palmcloud"                        # 占位文件后缀
WORK_DIR    = "/var/tmp/palm-archive"             # 打包临时区
MAGIC       = b"PALM"                             # 加密文件魔数
VER         = 1                                   # 加密格式版本


# ------------------------------------------------------------------ 工具
def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%F %T"), msg)
    print(line, flush=True)
    try:
        os.makedirs(INDEX_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def usage_pct(path):
    st = os.statvfs(path)
    used = st.f_blocks - st.f_bfree
    return 100.0 * used / st.f_blocks if st.f_blocks else 0.0


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f%s" % (n, u)
        n /= 1024.0
    return "%.1fPB" % n


# ------------------------------------------------------------------ 门户账号
def sync_portal_db():
    """从 CT103 导出 portal.db 副本（宿主可读）"""
    if not os.path.exists(PORTAL_DB) or time.time() - os.path.getmtime(PORTAL_DB) > 300:
        r = subprocess.run(
            ["pct", "exec", "103", "--", "cat", "/opt/portal/portal.db"],
            capture_output=True,
        )
        if r.returncode != 0 or not r.stdout:
            log("WARN: 无法从 CT103 导出 portal.db: %s" % r.stderr.decode()[:200])
            return False
        with open(PORTAL_DB, "wb") as f:
            f.write(r.stdout)
        log("已同步 portal.db (%d 字节)" % len(r.stdout))
    return True


def load_accounts():
    """返回 {username: {'pw': hex哈希, 'role': ...}}"""
    if not os.path.exists(PORTAL_DB):
        return {}
    con = sqlite3.connect(PORTAL_DB)
    try:
        rows = con.execute("SELECT username, pw, role FROM accounts").fetchall()
    except sqlite3.Error as e:
        log("WARN: 读 accounts 失败: %s" % e)
        return {}
    finally:
        con.close()
    return {u: {"pw": p, "role": r} for u, p, r in rows}


def visible_domains(accounts):
    """产出 (账号, 目录) —— public 归 owner"""
    owner = next((u for u, i in accounts.items() if i.get("role") == "owner"), None)
    pub = os.path.join(SRC_ROOT, "public")
    if owner and os.path.isdir(pub):
        yield owner, pub
    for acct in accounts:
        d = os.path.join(SRC_ROOT, "private", acct)
        if os.path.isdir(d):
            yield acct, d


# ------------------------------------------------------------------ 加密
def derive_key(pw_hash_hex, salt):
    """HKDF-SHA256(门户密码哈希, 随机盐) → 32 字节密钥"""
    ikm = bytes.fromhex(pw_hash_hex)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"palm-archive-v1",
    ).derive(ikm)


def encrypt_shard(src, dst, pw_hash_hex):
    """
    加密单个分片，输出格式:
      [MAGIC 4B][VER 1B][SALT 16B][NONCE 12B][CIPHERTEXT+TAG]
    返回 (sha256_of_ciphertext, salt_hex, nonce_hex)
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(pw_hash_hex, salt)
    aead = ChaCha20Poly1305(key)

    with open(src, "rb") as f:
        plain = f.read()
    ct = aead.encrypt(nonce, plain, None)

    with open(dst, "wb") as f:
        f.write(MAGIC + bytes([VER]) + salt + nonce + ct)

    return sha256_file(dst), salt.hex(), nonce.hex()


# ------------------------------------------------------------------ 文件表
def init_index():
    os.makedirs(INDEX_DIR, exist_ok=True)
    con = sqlite3.connect(INDEX_DB)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            domain        TEXT NOT NULL,
            rel_path      TEXT NOT NULL,
            size          INTEGER,
            mtime         REAL,
            sha256_plain  TEXT,
            archive_uri   TEXT NOT NULL,
            shard         TEXT,
            sha256_shard  TEXT,
            salt          TEXT,
            nonce         TEXT,
            archived_at   TEXT,
            UNIQUE(domain, rel_path)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_domain ON archived_files(domain)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_uri ON archived_files(archive_uri)")
    con.commit()
    return con


def list_index():
    if not os.path.exists(INDEX_DB):
        print("(文件表为空)")
        return
    con = sqlite3.connect(INDEX_DB)
    rows = con.execute(
        "SELECT domain, rel_path, size, archive_uri, archived_at "
        "FROM archived_files ORDER BY archived_at DESC, domain, rel_path"
    ).fetchall()
    con.close()
    print("%-12s %-42s %10s  %-46s %s" % ("域", "原路径", "大小", "归档位置", "归档时间"))
    print("-" * 140)
    for d, p, s, u, t in rows:
        print("%-12s %-42s %10s  %-46s %s" % (d, p, human(s or 0), u, t))


# ------------------------------------------------------------------ 归档主体
def collect_frags(root):
    """收集 < FRAG_MAX 的碎片文件（跳过占位文件）"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".palm")]
        for fn in filenames:
            if fn.endswith(STUB_SUFFIX):
                continue
            p = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz < FRAG_MAX:
                out.append((p, sz, os.path.getmtime(p)))
    return out


def write_stub(path, meta):
    """在原位置写占位文件"""
    stub = path + STUB_SUFFIX
    try:
        with open(stub, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return stub
    except OSError as e:
        log("  WARN: 写占位失败 %s: %s" % (stub, e))
        return None


def archive_domain(con, acct, root, pw_hash, stamp, dry=False):
    frags = collect_frags(root)
    if not frags:
        return 0, 0

    total = sum(s for _, s, _ in frags)
    log("[%s] 发现 %d 个碎片文件，合计 %s" % (acct, len(frags), human(total)))
    if dry:
        return len(frags), total

    outdir = os.path.join(DST_ROOT, acct, stamp)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    # --- 1) tar 打包
    tar_path = os.path.join(WORK_DIR, "%s-%s.tar" % (acct, stamp))
    log("  打包 → %s" % tar_path)
    with tarfile.open(tar_path, "w") as tar:
        for p, _, _ in frags:
            # 归档内路径统一为「相对 /mnt/palm」的完整路径，便于 palmfs 按需还原
            tar.add(p, arcname=os.path.relpath(p, SRC_ROOT))

    # --- 2) split 分片
    subprocess.run(
        ["split", "-b", str(SHARD_SIZE), "-d", "-a", "3",
         tar_path, os.path.join(WORK_DIR, "shard-")],
        check=True,
    )
    shards = sorted(
        os.path.join(WORK_DIR, f)
        for f in os.listdir(WORK_DIR)
        if f.startswith("shard-")
    )
    log("  切分 → %d 个分片" % len(shards))

    # --- 3) 加密每个分片 + 生成清单
    manifest = {
        "domain": acct,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(frags),
        "plain_total": total,
        "cipher": "ChaCha20-Poly1305",
        "kdf": "HKDF-SHA256(pw_hash, salt, info=palm-archive-v1)",
        "shards": [],
    }

    for idx, sh in enumerate(shards):
        enc_name = "shard-%03d.enc" % idx
        enc_path = os.path.join(outdir, enc_name)
        sha, salt, nonce = encrypt_shard(sh, enc_path, pw_hash)
        manifest["shards"].append(
            {"name": enc_name, "sha256": sha, "salt": salt,
             "nonce": nonce, "size": os.path.getsize(enc_path)}
        )
        log("  加密分片 %s (%s)" % (enc_name, human(os.path.getsize(enc_path))))

    # --- 4) 写清单
    mpath = os.path.join(outdir, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    subprocess.run(["sha256sum", mpath], check=False)

    # --- 5) 删本地 + 写文件表（占位视图由 palmfs 按需合成，不再落地 .palmcloud）
    archive_uri = "%s/%s/" % (acct, stamp)
    removed = 0
    for p, sz, mt in frags:
        rel = os.path.relpath(p, SRC_ROOT)          # 相对 /mnt/palm 的完整路径
        try:
            sha_plain = sha256_file(p)
        except OSError:
            sha_plain = ""
        try:
            os.remove(p)
            removed += 1
        except OSError as e:
            log("  WARN: 删除失败 %s: %s" % (p, e))
        con.execute(
            """INSERT OR REPLACE INTO archived_files
               (domain, rel_path, size, mtime, sha256_plain, archive_uri,
                shard, sha256_shard, salt, nonce, archived_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (acct, rel, sz, mt, sha_plain, archive_uri,
             None, None, None, None, manifest["created_at"]),
        )
    con.commit()

    # --- 6) 清理临时
    try:
        os.remove(tar_path)
        for sh in shards:
            os.remove(sh)
    except OSError:
        pass

    log("[%s] 完成: 归档 %d 个文件 → %s, 删除本地 %d 个"
        % (acct, len(frags), outdir, removed))
    return len(frags), total


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略阈值强制归档")
    ap.add_argument("--dry-run", action="store_true", help="只扫描不动作")
    ap.add_argument("--list", action="store_true", help="打印文件表")
    args = ap.parse_args()

    if args.list:
        list_index()
        return 0

    pct = usage_pct(HDD_MONITOR)
    log("HDD 使用率 %.1f%% (阈值 %d%%)" % (pct, THRESHOLD))
    if pct < THRESHOLD and not args.force:
        log("未达阈值，跳过")
        return 0

    if not sync_portal_db():
        log("ERROR: 无门户账号库，退出")
        return 1
    accounts = load_accounts()
    if not accounts:
        log("ERROR: accounts 为空，退出")
        return 1
    log("门户账号: %s" % ", ".join("%s(%s)" % (u, i["role"]) for u, i in accounts.items()))

    con = init_index()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tf = tt = 0
    for acct, root in visible_domains(accounts):
        n, sz = archive_domain(con, acct, root, accounts[acct]["pw"], stamp, args.dry_run)
        tf += n
        tt += sz
    con.close()

    log("全部完成: 共 %d 个文件, %s%s" % (tf, human(tt), " (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
