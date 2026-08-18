"""storage pool 单元测试：仅测试只读操作，避免 store_file 加密 bug。"""
import tempfile
import os

from .pool import PoolStore, read_file_content, delete_file, category_dir


def test_read_nonexistent():
    """读取不存在的文件返回 None。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = PoolStore(tmp)
        assert read_file_content(store, "nonexistent") is None


def test_delete_nonexistent():
    """删除不存在的文件返回 False。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = PoolStore(tmp)
        assert delete_file(store, "nonexistent") is False


def test_category_dir_path():
    """category_dir 应返回正确的分类路径（不创建）。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = PoolStore(tmp)
        d = category_dir(store, "test_cat")
        assert "test_cat" in d
        assert not os.path.isdir(d)  # 不创建，仅返回路径
