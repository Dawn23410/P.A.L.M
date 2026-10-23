"""Ollama 工作区：模型目录 / 下载器 / 格式转换 / 连接探测 / 安装向导。

自 P.A.L.M 主工程 `palm/adapters/model/ollama/` 整体迁入（2026-09-10）。
只依赖标准库；主工程在场时连接探测走网卡门面，独立部署时标准库直连 localhost。
"""
from . import (catalog, catalog_data, connection, convert, downloader,
               ollama_guide)

__all__ = ["catalog", "catalog_data", "connection", "convert", "downloader",
           "ollama_guide"]
