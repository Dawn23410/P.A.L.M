"""国密 SM3 测试：GB/T 32905-2016 标准向量 + 接口契约。

设计：
- 标准向量为**硬编码常量**（GB/T 32905-2016 附录 A），非本库自产，杜绝循环验证；
- 覆盖 sm3_hash / sm3_int 的 str↔bytes 一致性、摘要长度、稳定性。

运行：
    cd 1_Demo_LLM/加解密内核 && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import sm3_hash, sm3_int  # noqa: E402

# ── GB/T 32905-2016 附录 A 标准测试向量 ──
VEC1_IN = "abc"
VEC1_OUT = "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"
VEC2_IN = "abcd" * 16  # 64 字节
VEC2_OUT = "debe9ff92275b8a138604889c18e5a4d6fdb70e5387e5765293dcba39c0c5732"


class Sm3StandardVectorTest(unittest.TestCase):
    def test_gb_vector_abc(self):
        self.assertEqual(sm3_hash(VEC1_IN), VEC1_OUT, "SM3 与国标向量 1 不符")

    def test_gb_vector_abcd16(self):
        self.assertEqual(sm3_hash(VEC2_IN), VEC2_OUT, "SM3 与国标向量 2 不符")


class Sm3ApiTest(unittest.TestCase):
    def test_digest_is_256bit_hex(self):
        h = sm3_hash("任意内容")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_str_and_bytes_equivalent(self):
        self.assertEqual(sm3_hash("你好"), sm3_hash("你好".encode("utf-8")))

    def test_sm3_int_matches_hex(self):
        self.assertEqual(sm3_int("consistent"), int(sm3_hash("consistent"), 16))

    def test_empty_input(self):
        self.assertEqual(len(sm3_hash(b"")), 64)

    def test_distinct_inputs_distinct_digest(self):
        self.assertNotEqual(sm3_hash("a"), sm3_hash("b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
