"""CosyVoice 砖包：导入即触发注册（完整砖，进程内持有模型）。

音色创造专用——本地 CosyVoice2 推理（完整砖，进程内持有模型，非薄代理），与 GSV 互补：
本砖用自然语言描述「造」出参考音频，GSV 经 refer_wav_path 克隆该音色做实时合成。
cosyvoice 重依赖懒导入，未安装时优雅降级，不影响 P.A.L.M 启动。
"""
try:
    from . import brick  # noqa: F401
except Exception:
    # 砖块仅在完整 P.A.L.M（含 app 包）运行时注册 HTTP 路由；独立使用（如离线造音脚本
    # 直接 import engine）时仅 engine 可用，跳过注册不报错。
    pass

__all__ = ["brick"]
