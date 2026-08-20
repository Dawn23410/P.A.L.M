"""拆分中间件测试：消费字段 / 外发字段 / 正文清洗。"""
from mentalcore.middleware.split import ReplySplitter


def test_split_consumed_and_out():
    raw = '我是梦瑶。你刚才说「你好」。\n||DATA||{"affinity_delta":2,"inner_note":"偷着乐"}||END||'
    splitter = ReplySplitter()
    body, out, consumed = splitter.split(raw)
    assert "||DATA||" not in body
    assert consumed.get("affinity_delta") == 2
    assert out.get("inner_note") == "偷着乐"
    assert "affinity_delta" not in out


def test_split_no_data():
    raw = "普通回复，无数据区。"
    splitter = ReplySplitter()
    body, out, consumed = splitter.split(raw)
    assert body == raw
    assert out == {}
    assert consumed == {}


def test_split_malformed_data():
    raw = '正文||DATA||{坏json}||END||'
    splitter = ReplySplitter()
    body, out, consumed = splitter.split(raw)
    assert body.startswith("正文")
    assert out == {}
