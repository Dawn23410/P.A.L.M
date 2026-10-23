#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份进度看门狗 —— 每 10 分钟采样一次, 追加到 progress.log
采样指标: NAS 剩余空间(瞬间 API) -> 反推已备份体积; 外加 backup.log 最后一行
用法: python watch_progress.py
"""
import os, sys, time, shutil, datetime

TARGET_DRIVE = 'Z:\\'
BACKUP_LOG   = r'C:\Users\24459\Desktop\PALM_Backup\backup.log'
OUT          = r'C:\Users\24459\Desktop\PALM_Backup\progress.log'
INTERVAL     = 600          # 10 分钟
BASE_FREE    = None

def line(msg):
    s = '%s  %s' % (datetime.datetime.now().strftime('%m-%d %H:%M:%S'), msg)
    print(s, flush=True)
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(s + '\n')

def last_backup_line():
    try:
        with open(BACKUP_LOG, 'r', encoding='utf-8', errors='replace') as f:
            ls = f.readlines()
        for l in reversed(ls):
            if '已复制' in l or '新增' in l or '总计' in l:
                return l.strip()
        return ls[-1].strip() if ls else '(日志为空)'
    except OSError as e:
        return '(读日志失败: %s)' % e

def main():
    global BASE_FREE
    line('看门狗启动, 每 %d 分钟采样一次' % (INTERVAL // 60))
    try:
        BASE_FREE = shutil.disk_usage(TARGET_DRIVE).free
        line('NAS 初始剩余: %.1f GB' % (BASE_FREE / 2**30))
    except OSError as e:
        line('无法读取 %s: %s' % (TARGET_DRIVE, e)); return 1
    while True:
        time.sleep(INTERVAL)
        try:
            free = shutil.disk_usage(TARGET_DRIVE).free
            used = BASE_FREE - free
            line('已备份 ≈ %.2f GB  |  NAS 剩余 %.1f GB  |  %s'
                 % (used / 2**30, free / 2**30, last_backup_line()))
        except OSError as e:
            line('采样失败: %s' % e)

if __name__ == '__main__':
    sys.exit(main())
