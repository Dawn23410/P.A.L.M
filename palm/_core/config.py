# 独立态配置：环境变量代理，含少量运行时默认路径。
# 主板治理层在导入期即用 Path(settings.STORAGE_POOL_DIR) 构造审计/信任目录，
# 故为关键路径提供默认值，避免独立运行态因未设环境变量而导入失败。
import os
from pathlib import Path

# 项目根（palm_sdk/core/config.py → palm_sdk → 根）。
_ROOT = Path(__file__).resolve().parents[2]

# 独立态默认路径：仅当对应环境变量未设置时生效；单体运行态会自行覆盖。
# 缺省指向 Data/ 下独立子目录，使各砖在「未配置运行态」下仍能优雅降级
# （路径合法但资源不存在 → 端点返回 404/available=false，而非因 None 崩 500）。
# GSV 砖的 SOVITS_* 缺省直接指向砖内已分发源码与已内聚权重，使未配置 .env
# 时仍能构造合法的子进程启动命令（避免 None 拼接路径触发 TypeError 503 降级）。
# 注：api.py 在 src/gpt_sovits/api.py，启动 cwd 必须是 src/gpt_sovits（它把
# cwd/GPT_SoVITS 加入 sys.path 找 text 模块），故 ROOT 取 gpt_sovits 层。
_GSV_SRC = _ROOT / "语音合成 (GPT-SoVITS)" / "src" / "gpt_sovits"
_GSV_MODELS = _GSV_SRC / "pretrained_models"
_DEFAULTS = {
    "STORAGE_POOL_DIR": str(_ROOT / "Data" / "storage_pool"),
    "SOVITS_OUTPUT_DIR": str(_ROOT / "Data" / "tts_sovits_output"),
    "COSY_OUTPUT_DIR": str(_ROOT / "Data" / "cosy_output"),
    "UPLOAD_DIR": str(_ROOT / "Data" / "uploads"),
    # GSV 语音合成（独立态默认：砖内源码 + 内聚权重，可被 .env 覆盖）。
    "SOVITS_ROOT": str(_GSV_SRC),
    "SOVITS_API_PORT": "9880",
    "SOVITS_INFER_DEVICE": "cuda",
    "SOVITS_API_ROUTE": "/",
    "SOVITS_API_URL": "http://127.0.0.1:9880",
    "SOVITS_SOVITS_MODEL": "pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    "SOVITS_GPT_MODEL": "pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "SOVITS_HUBERT_DIR": "pretrained_models/chinese-hubert-base",
    "SOVITS_BERT_DIR": "pretrained_models/chinese-roberta-wwm-ext-large",
    "SOVITS_DEFAULT_REFER_WAV": "ref_audio.wav",
    "SOVITS_DEFAULT_REFER_TEXT": "你好，我是语音助手。",
    "SOVITS_DEFAULT_REFER_LANG": "zh",
}


class _Settings:
    """按属性名读环境变量；未设置则返回默认值（仍允许环境变量覆盖）。"""

    def __getattr__(self, name: str):
        if name in _DEFAULTS:
            return os.environ.get(name, _DEFAULTS[name])
        return os.environ.get(name)

    def __contains__(self, name: str) -> bool:
        return name in os.environ

    def get(self, name: str, default=None):
        return os.environ.get(name, default)


settings = _Settings()
