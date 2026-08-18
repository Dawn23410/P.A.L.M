"""存储砖管理芯片：配额 / 生命周期 / 审计 / 健康监测。

各模块只操作 PoolStore（经 transaction 落盘），不跨砖 import；对外经砖 capabilities 暴露，
消费方（含 sandbox）一律经存储砖 capability 取用，依赖方向 sandbox → 存储砖。

子模块按需直接导入（如 `from .controller.quota import reserve_bytes`），本包不急于全部加载，
避免尚未实现的生命周期/审计/健康模块拖慢启动或形成导入环。
"""
from __future__ import annotations
