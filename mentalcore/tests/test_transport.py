"""传输包与控制码测试。"""
import pytest

from mentalcore.transport import ControlCode, TransportPacket, INTENT_ROUTES


def test_control_code_parse():
    c = ControlCode(10000)
    assert c.d1 == 1 and c.d2 == 0 and c.d3 == 0 and c.d4 == 0 and c.d5 == 0
    assert c.domain_name() == "储存"
    assert c.subclass_name() == "对话记录"
    assert c.action_name() == "查"


def test_control_code_describe():
    assert ControlCode(10100).describe() == "储存·对话记录·清·全部·请求"
    assert ControlCode(13000).describe() == "储存·加密状态·查·全部·请求"


def test_control_code_make():
    c = ControlCode.make(1, 1, 1, 0, 1)
    assert c.code == 11101


def test_intent_routes():
    assert INTENT_ROUTES["清对话记录"] == 10100
    assert INTENT_ROUTES["查加密状态"] == 13000
    assert INTENT_ROUTES["查模型信息"] is None


def test_transport_packet():
    p = TransportPacket(body="hi", fields={"a": 1})
    assert p.to_dict() == {"body": "hi", "fields": {"a": 1}}
