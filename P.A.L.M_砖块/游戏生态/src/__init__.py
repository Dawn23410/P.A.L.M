"""game 砖包：导入即注册。

已落地「游戏性生态」——经验系统（10 阶 × 100 级等级推导、每日登录打卡、
聊天/特殊任务经验结算、好感度系数、星砂货币、商城道具）。
纯逻辑在 xp.py，状态落盘在 state.py；好感度系数经 affection 砖 capabilities 取，
不直接 import 角色卡/记忆层（缺失降级 1.0）。
"""
from .brick import brick

__all__ = ["brick"]
