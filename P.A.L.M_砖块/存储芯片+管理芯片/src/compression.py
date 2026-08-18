"""存储池无损压缩：落盘前对明文做 DEFLATE 压缩（zlib，Python 标准库，无额外依赖）。

与加密正交、位于其下层：写链路为「明文 → 压缩 → 加密」，读链路为「解密 → 解压 → 明文」。
如此加密仍对密文生效，且压缩能受益于明文冗余（加密后的数据近似随机、不可压）。
仅当压缩后体积更小才落压缩版（图片/视频等已压缩二进制不浪费 CPU），由 FileRecord.compressed 标记，保证旧文件可读。
"""
from __future__ import annotations

import zlib

# 压缩级别：6 为 zlib 默认，兼顾比速；纯标准库，无需安装二进制依赖。
COMPRESSION_LEVEL = 6


def compress_bytes(content: bytes) -> bytes:
    """明文 → DEFLATE(zlib 格式) 字节；调用方自行判断压缩是否划算再落盘。"""
    return zlib.compress(content, COMPRESSION_LEVEL)


def decompress_bytes(data: bytes) -> bytes:
    """DEFLATE(zlib 格式) 字节 → 明文；解压失败抛 zlib.error 由调用方处理。"""
    return zlib.decompress(data)
