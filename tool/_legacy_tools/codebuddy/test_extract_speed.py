"""
整合包解压速度测试脚本
========================
测试 .gsvp 文件从复制到解压完成的完整耗时。

用法:
  python test_extract_speed.py <路径/包名.gsvp>

示例:
  python test_extract_speed.py D:/models/my_voice.gsvp
"""

import sys
import os
import time
import shutil
import tempfile

# 确保能找到 runtime/server.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'runtime'))

from server import read_file_bytes, extract_gsvp, MAGIC_GSVP

def fmt_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'

def main():
    if len(sys.argv) < 2:
        print()
        print("  ╔══════════════════════════════════════════════╗")
        print("  ║   整合包解压速度测试                         ║")
        print("  ╚══════════════════════════════════════════════╝")
        print()
        print(f"  用法: {sys.argv[0]} <路径/包名.gsvp>")
        print()
        print(f"  示例: python test_extract_speed.py /path/to/model.gsvp")
        print()
        sys.exit(1)

    src_path = sys.argv[1]

    if not os.path.isfile(src_path):
        print(f"  [ERROR] 文件不存在: {src_path}")
        sys.exit(1)

    file_size = os.path.getsize(src_path)
    print()
    print(f"  文件: {os.path.basename(src_path)}")
    print(f"  大小: {fmt_size(file_size)}")
    print()

    # ── 阶段1: 读取文件 ──
    print("  [1/5] 读取文件到内存...", end=' ', flush=True)
    t0 = time.time()
    data = read_file_bytes(src_path)
    t1 = time.time()
    read_time = t1 - t0
    read_speed = file_size / read_time / 1024 / 1024 if read_time > 0 else 0
    print(f"完成 ({read_time:.2f}s, {read_speed:.0f} MB/s)")

    # ── 阶段2: 验证魔数 + 显示 header ──
    print("  [2/5] 验证魔数...", end=' ', flush=True)
    if data[:6] == MAGIC_GSVP:
        print("通过 ✓")
        # 显示 header 二进制信息用于调试
        import struct
        ver_raw = struct.unpack_from('<H', data, 6)[0]
        hdr_raw = struct.unpack_from('<I', data, 8)[0]
        xor_raw = struct.unpack_from('<H', data, 12)[0]
        print(f"        header: version={ver_raw}  header_len={hdr_raw}  xor_key={xor_raw}")
        print(f"        raw[6:14]: {data[6:14].hex(' ')}")
    else:
        print("失败 ✗ (无效的整合包)")
        print(f"        MAGIC: {data[:6].hex(' ')} (期望: {MAGIC_GSVP.hex(' ')})")
        sys.exit(1)

    # ── 阶段3: 复制到目标目录 ──
    test_dir = os.path.join(os.path.dirname(__file__), 'runtime', 'packages', '__speed_test__')
    os.makedirs(test_dir, exist_ok=True)
    dest_path = os.path.join(test_dir, os.path.basename(src_path))

    print("  [3/5] 复制到 packages 目录...", end=' ', flush=True)
    t0 = time.time()
    shutil.copy2(src_path, dest_path)
    t1 = time.time()
    copy_time = t1 - t0
    copy_speed = file_size / copy_time / 1024 / 1024 if copy_time > 0 else 0
    print(f"完成 ({copy_time:.2f}s, {copy_speed:.0f} MB/s)")

    # ── 阶段4: 解压 ──
    extract_dir = os.path.join(test_dir, 'extracted')
    print("  [4/5] 解压文件...", end=' ', flush=True)
    t0 = time.time()
    extract_gsvp(data, extract_dir, debug=True)
    t1 = time.time()
    extract_time = t1 - t0

    # 计算解压后的总大小
    extracted_size = 0
    extracted_count = 0
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            extracted_size += os.path.getsize(os.path.join(root, f))
            extracted_count += 1
    extract_speed = extracted_size / extract_time / 1024 / 1024 if extract_time > 0 else 0

    print(f"完成 ({extract_time:.2f}s)")
    print(f"      解压文件数: {extracted_count}")
    print(f"      解压后大小: {fmt_size(extracted_size)}")
    print(f"      写入速度:   {extract_speed:.0f} MB/s")

    # ── 阶段5: 清理 ──
    print("  [5/5] 清理临时文件...", end=' ', flush=True)
    shutil.rmtree(test_dir, ignore_errors=True)
    print("完成")

    # ── 汇总 ──
    total = read_time + copy_time + extract_time
    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║              测 试 汇 总                     ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()
    print(f"  读取:   {read_time:.2f}s   ({read_speed:.0f} MB/s)")
    print(f"  复制:   {copy_time:.2f}s   ({copy_speed:.0f} MB/s)")
    print(f"  解压:   {extract_time:.2f}s   ({extract_speed:.0f} MB/s)")
    print(f"  ─────────────────────────────")
    print(f"  总计:   {total:.2f}s")
    print()

    # 判断瓶颈
    bottleneck = max(read_time, copy_time, extract_time)
    if bottleneck == read_time:
        print(f"  ⚠ 瓶颈: 读取阶段 (磁盘读取速度)")
    elif bottleneck == copy_time:
        print(f"  ⚠ 瓶颈: 复制阶段 (磁盘写入速度)")
    else:
        print(f"  ⚠ 瓶颈: 解压阶段 (文件解析 + 磁盘写入)")
    print()

if __name__ == '__main__':
    main()
