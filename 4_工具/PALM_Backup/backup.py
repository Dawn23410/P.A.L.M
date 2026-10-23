#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PALM 重装前备份器 —— 把本机重要资料复制到 NAS(Z:)
特性: 可续传(同大小即跳过) / 中文路径安全 / 全部失败落盘 / 只复制不删除
用法: python backup.py            正常备份(可反复跑, 已备好的会跳过)
      python backup.py --verify   只核对: 源文件在目标是否存在且大小一致
      python backup.py --dry      只统计不复制
"""
import os, sys, shutil, time, datetime

DST_ROOT = r'Z:\_backup_20261009'
LOG      = r'C:\Users\24459\Desktop\PALM_Backup\backup.log'
FAILLOG  = r'C:\Users\24459\Desktop\PALM_Backup\failures.txt'
DRY      = '--dry' in sys.argv
VERIFY   = '--verify' in sys.argv

# (源, 目标子目录)  —— 不存在会自动跳过
SRC = [
    ('D:\\',                                r'D'),
    (r'C:\Users\24459\Desktop',            r'C\Desktop'),
    (r'C:\Users\24459\Documents',          r'C\Documents'),
    (r'C:\Users\24459\Downloads',          r'C\Downloads'),
    (r'C:\Users\24459\Pictures',           r'C\Pictures'),
    (r'C:\Users\24459\Videos',             r'C\Videos'),
    (r'C:\Users\24459\Music',              r'C\Music'),
    (r'C:\Users\24459\PycharmProjects',    r'C\PycharmProjects'),
    (r'C:\Users\24459\source',             r'C\source'),
    (r'C:\Users\24459\Tools',              r'C\Tools'),
    (r'C:\Users\24459\GPT_SoVITS',         r'C\GPT_SoVITS'),
    (r'C:\Users\24459\Genshin_Dataset',    r'C\Genshin_Dataset'),
    (r'C:\Users\24459\ros2-offline',       r'C\ros2-offline'),
    (r'C:\Users\24459\wsl-distros',        r'C\wsl-distros'),
    (r'C:\Users\24459\.ssh',               r'C\.ssh'),
    (r'C:\Users\24459\.config',            r'C\.config'),
    (r'C:\Users\24459\.dsh',               r'C\.dsh'),
    (r'C:\Users\24459\.ollama',            r'C\.ollama'),
    (r'C:\Users\24459\.modelscope',        r'C\.modelscope'),
    (r'C:\Users\24459\.palm-llm',          r'C\.palm-llm'),
    (r'C:\Users\24459\.palm-memory',       r'C\.palm-memory'),
    (r'C:\Users\24459\.workbuddy',         r'C\.workbuddy'),
    (r'C:\Users\24459\.workbuddy-ai',      r'C\.workbuddy-ai'),
    (r'C:\Users\24459\.workbuddy-key-fallback', r'C\.workbuddy-key-fallback'),
    (r'C:\Users\24459\OneDrive',           r'C\OneDrive'),
    (r'C:\Users\24459\WorkBuddy',          r'C\WorkBuddy'),
    (r'C:\Users\24459\WorkBuddy AI',       r'C\WorkBuddy AI'),
    # TeleAgent 相关
    (r'C:\Users\24459\AppData\Roaming\TeleAgent', r'C\AppData_Roaming_TeleAgent'),
    (r'C:\Users\24459\AppData\Local\TeleAgent',   r'C\AppData_Local_TeleAgent'),
    (r'C:\Program Files\TeleAgent',               r'ProgramFiles_TeleAgent'),
]

SKIP_DIRS = {'$RECYCLE.BIN', 'System Volume Information', '$SysReset', 'Recovery'}

_log = None
_fail = None
def log(msg):
    global _log
    line = '%s %s' % (datetime.datetime.now().strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    if _log is None:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        _log = open(LOG, 'a', encoding='utf-8')
    _log.write(line + '\n'); _log.flush()

def faillog(msg):
    global _fail
    if _fail is None:
        _fail = open(FAILLOG, 'a', encoding='utf-8')
    _fail.write('%s %s\n' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg))
    _fail.flush()

def copy_tree(src, dst):
    n_new = n_skip = n_fail = n_miss = n_diff = 0
    bytes_new = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        tgt = dst if rel == '.' else os.path.join(dst, rel)
        if VERIFY:
            for f in files:
                s = os.path.join(root, f); d = os.path.join(tgt, f)
                try:
                    ss = os.path.getsize(s)
                    if not os.path.exists(d):
                        n_miss += 1; faillog('[缺失] %s' % s)
                    elif os.path.getsize(d) != ss:
                        n_diff += 1; faillog('[大小不符] %s (源%d 目标%d)' % (s, ss, os.path.getsize(d)))
                    else:
                        n_skip += 1
                except OSError as e:
                    n_fail += 1; faillog('[核对失败] %s (%s)' % (s, e))
            continue
        try:
            os.makedirs(tgt, exist_ok=True)
        except OSError as e:
            faillog('[建目录失败] %s (%s)' % (tgt, e))
        for f in files:
            s = os.path.join(root, f); d = os.path.join(tgt, f)
            try:
                ss = os.path.getsize(s)
                if os.path.exists(d) and os.path.getsize(d) == ss:
                    n_skip += 1; continue
                if DRY:
                    n_new += 1; bytes_new += ss; continue
                shutil.copy2(s, d)
                n_new += 1; bytes_new += ss
                if n_new % 500 == 0:
                    log('    ... 已复制 %d 个文件 (%.2f GB) 失败%d' % (n_new, bytes_new / 2**30, n_fail))
            except OSError as e:
                n_fail += 1
                faillog('[复制失败] %s (%s)' % (s, e))
                if n_fail <= 20:
                    log('    !! 失败: %s (%s)' % (s, e))
    return n_new, n_skip, n_fail, bytes_new, n_miss, n_diff

def main():
    log('=' * 70)
    mode = '核对' if VERIFY else ('[DRY RUN]' if DRY else '备份')
    log('PALM %s开始 -> %s' % (mode, DST_ROOT))
    g = {'new':0,'skip':0,'fail':0,'bytes':0,'miss':0,'diff':0}
    t0 = time.time()
    for src, sub in SRC:
        if not os.path.exists(src):
            log('  跳过(不存在): %s' % src); continue
        dst = os.path.join(DST_ROOT, sub)
        log('[%s] -> %s' % (src, dst))
        a, b, c, d, m, df = copy_tree(src, dst)
        g['new']+=a; g['skip']+=b; g['fail']+=c; g['bytes']+=d; g['miss']+=m; g['diff']+=df
        log('    新增 %d / 跳过 %d / 失败 %d  (%.2f GB)' % (a, b, c, d / 2**30))
    el = time.time() - t0
    log('-' * 70)
    if VERIFY:
        log('核对结果: 一致 %d, 缺失 %d, 大小不符 %d, 核对失败 %d'
            % (g['skip'], g['miss'], g['diff'], g['fail']))
        log('缺失/不符明细见: %s' % FAILLOG)
    else:
        log('总计: 新增 %d 个文件, 跳过 %d, 失败 %d, 共 %.2f GB, 用时 %.1f 分钟'
            % (g['new'], g['skip'], g['fail'], g['bytes'] / 2**30, el / 60))
        if g['bytes'] and el:
            log('平均速度: %.1f MB/s' % (g['bytes'] / 2**20 / el))
        log('失败明细见: %s' % FAILLOG)
    log('%s结束' % mode)
    return 0 if (g['fail'] + g['miss'] + g['diff']) == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
