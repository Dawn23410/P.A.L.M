"""Ollama 代理砖块：import 即注册。"""
from __future__ import annotations

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.permission import PermissionSpec, RiskLevel
from .brick import router

brick = Brick(
    manifest=BrickManifest(
        name="ollama",
        title="Ollama 向导代理",
        description="本机 Ollama 的全部引导能力：/guide 规格与安装检测、/health 运行检测、/catalog 模型目录（国内镜像+魔搭双来源）、/download 后台分片断点续传下载与进度轮询、/upload 拖拽 GGUF、/deploy 部署（Modelfile+高级参数）、/pull 与 /import-gguf 兼容旧路径。前端「引导」向导仅据此收集用户输入。",
        bus_type="pcie",
        can_accept_files=True,
    ),
    router=router,
    permissions=[
        PermissionSpec(key="ollama.pull_model", title="拉取/下载模型",
                        description="从网络拉取、下载或导入大模型权重（可能很大、耗时且占带宽）。",
                        risk=RiskLevel.HIGH, brick="ollama"),
        PermissionSpec(key="ollama.deploy_model", title="上传/部署模型",
                        description="将本地 GGUF 模型上传到 Ollama 并部署为可用模型。",
                        risk=RiskLevel.MEDIUM, brick="ollama"),
    ],
)
registry.register(brick)