#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
palm-authsync — 按门户认证表动态生成「每账号一个 Samba 共享」
================================================================
原理：
  门户(CT103)登录成功后会把 (IP, 账号) 写进 portal.db 的 authed 表。
  本守护进程轮询该表，为每个账号生成一个 Samba 共享：
      [321801]  →  \\192.168.20.252\321801
  并用 hosts allow 精确放行「该账号已认证的那些 IP」——实现：
    · 免密（guest ok，不设密码）
    · 只有登录过该账号的设备(IP)才能访问
    · 单账号多设备天然支持（一个账号多个 IP 全部放行）

  一个账号在几台设备登录，就有几个 IP 进白名单；注销/换设备由门户表自然更新。
"""

import os
import sys
import time
import sqlite3
import hashlib
import subprocess

PORTAL_DB = "/mnt/palm/.palm/portal.db"       # 宿主同步过来的门户库副本
OUT       = "/etc/samba/palm-shares.conf"      # 动态生成的共享定义
BASE      = "/mnt/storage/private"             # 个人域根
SHARED    = "共享"                             # 个人域内的共享子目录(符号链接)
INTERVAL  = 15                                 # 轮询间隔(秒)

SHARE_TMPL = """
[{acct}]
    comment = {acct} 的个人空间
    path = {path}
    browseable = yes
    read only = no
    guest ok = yes
    force user = root
    wide links = yes
    follow symlinks = yes
    create mask = 0777
    directory mask = 0777
    hosts allow = {ips}
    hosts deny = 0.0.0.0/0
    vfs objects = full_audit
    full_audit:prefix = %u|%I|%S
"""


def log(msg):
    print("[authsync] %s" % msg, flush=True)


def load_authed():
    """返回 {账号: {ip, ...}}"""
    if not os.path.exists(PORTAL_DB):
        return {}
    try:
        con = sqlite3.connect(PORTAL_DB, timeout=10)
        rows = con.execute(
            "SELECT ip, account FROM authed "
            "WHERE account IS NOT NULL AND account != ''"
        ).fetchall()
        con.close()
    except sqlite3.Error as e:
        log("读门户库失败: %s" % e)
        return {}
    d = {}
    for ip, acct in rows:
        ip = (ip or "").strip()
        if ip:
            d.setdefault(acct, set()).add(ip)
    return d


def render(authed):
    parts = [
        "# ============================================================",
        "# 由 palm-authsync 自动生成，请勿手动修改",
        "# 每个账号一个 Samba 共享；hosts allow 精确放行其已认证 IP",
        "# ============================================================",
        "",
    ]
    for acct in sorted(authed):
        path = os.path.join(BASE, acct)
        if not os.path.isdir(path):
            continue
        ips = " ".join(sorted(authed[acct]))
        parts.append(SHARE_TMPL.format(acct=acct, path=path, ips=ips))
    return "\n".join(parts)


def main():
    log("启动，监控 %s（间隔 %ds）" % (PORTAL_DB, INTERVAL))
    last_hash = None
    while True:
        try:
            authed = load_authed()
            content = render(authed)
            h = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if h != last_hash:
                with open(OUT, "w", encoding="utf-8") as f:
                    f.write(content)
                subprocess.run(["smbcontrol", "all", "reload-config"],
                               check=False, capture_output=True)
                total = sum(len(v) for v in authed.values())
                log("已更新: %d 个账号, %d 个已认证 IP -> %s"
                    % (len(authed), total, OUT))
                for a in sorted(authed):
                    log("   [%s] allow: %s" % (a, " ".join(sorted(authed[a]))))
                last_hash = h
        except Exception as e:
            log("异常: %s" % e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
