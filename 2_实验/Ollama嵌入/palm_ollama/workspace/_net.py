"""兼容转发：实现已上提至包级 `palm_ollama._net`（工作区与嵌入共用一份）。

原实现只服务本工作区（localhost 探测 + 模型文件下载），现统一由包级提供，
本模块保留以维持既有导入路径（`from ._net import request`）不变。
"""
from .._net import USES_HOST_NET, is_card_present, request  # noqa: F401

__all__ = ["request", "is_card_present", "USES_HOST_NET"]
