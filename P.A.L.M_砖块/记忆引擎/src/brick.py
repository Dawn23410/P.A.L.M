"""记忆砖：注册 + 对外暴露 memory_api 门面。

原属 agent 砖的「记忆」域（长期归档 / 核心记忆 / 向量语义检索 / Token 预算 / 压缩），
现抽为独立砖。所有符号经 capabilities["memory_api"] 暴露，供 agent / evolution 经
app.bricks._shared.interop.get_memory_api() 取用，保持砖间零互导。

无启动副作用：纯数据与文件持久化，由 Memory 实例在会话生命周期内 initialize/shutdown。
"""
from __future__ import annotations

import sys

from palm_sdk.bricks.base import Brick, BrickManifest, registry

# memory_api 即本砖包对象：__init__ 已把全部符号（Memory / CoreMemory /
# purge_vector_by_conv_id / TokenBudgetAllocator 等）挂为包属性，consumers 直接取用。
memory_api = sys.modules[__package__]

brick = Brick(
    manifest=BrickManifest(
        name="memory",
        title="记忆引擎",
        description="长期归档 / 核心记忆 / 向量语义检索 / Token 预算 / 短长期上下文压缩。",
        bus_type="sata",
    ),
    capabilities={
        "memory_api": memory_api,
    },
)

registry.register(brick)