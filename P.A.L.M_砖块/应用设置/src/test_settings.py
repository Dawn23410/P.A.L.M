"""settings 单元测试：保存/加载 round-trip。"""
import os
import tempfile
import importlib

import pytest


def _get_brickmod():
    """通过 importlib 获取 settings.brick 模块（避开 __init__.py 的属性覆盖）。"""
    return importlib.import_module("backend.app.bricks.settings.brick")


def _patch_no_crypto(mod):
    """monkeypatch 加密能力为空，避免 crypto 砖空砖干扰。"""
    mod._crypto_capabilities = lambda: (None, None)


def test_save_load():
    """使用临时文件测试设置保存与加载。"""
    mod = _get_brickmod()
    _patch_no_crypto(mod)
    old_path = mod.SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        test_path = os.path.join(tmp, "settings.json")
        mod.SETTINGS_PATH = test_path
        try:
            payload = {"theme": "dark", "maxTokens": 4096, "agentWebSearch": False}
            mod.save_app_settings(payload)
            loaded = mod.load_app_settings()
            assert loaded == payload
        finally:
            mod.SETTINGS_PATH = old_path


def test_save_invalid():
    """保存非 dict 数据应抛 ValueError。"""
    mod = _get_brickmod()
    with pytest.raises(ValueError):
        mod.save_app_settings("not_a_dict")


def test_load_empty():
    """文件不存在时返回空 dict。"""
    mod = _get_brickmod()
    _patch_no_crypto(mod)
    old_path = mod.SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        test_path = os.path.join(tmp, "nonexistent.json")
        mod.SETTINGS_PATH = test_path
        try:
            loaded = mod.load_app_settings()
            assert loaded == {}
        finally:
            mod.SETTINGS_PATH = old_path
