"""CosyVoice2 引擎（完整砖，进程内持有模型，非薄代理）。

侧重点是音色创造：用一段基底参考音频 + 自然语言风格描述，经 instruct2 产出可克隆
参考音频（.wav + .txt + .json），供 GSV（GPT-SoVITS）经 refer_wav_path 克隆做实时合成。

与「薄代理」模式相反：本模块直接持有 CosyVoice2 模型并在砖进程内推理，不委派给任何
外部 HTTP 服务，不经 client/serve 代理。cosyvoice 重依赖在首次调用时懒导入，未安装时
capability 优雅降级（不阻断 P.A.L.M 启动）；模型懒加载，避免常驻占显存。
"""
from __future__ import annotations

import glob
import json
import os
import time
from pathlib import Path

try:
    from palm_sdk.core.config import settings
except Exception:
    # 独立砖块模式（无 monolith app 包，例如 backend/ 已归档）：改读环境变量，
    # 默认值与 monolith 的 config.py 保持一致，行为不变。
    settings = None

try:
    from palm_sdk.core.logging import get_logger
except Exception:
    import logging

    def get_logger(name: str):  # type: ignore[no-redef]
        return logging.getLogger(name)

logger = get_logger(__name__)

# 懒加载的单例：首次造音时才把 CosyVoice2 装进本进程。
_ENGINE = None

# 本机 onnxruntime 仅 Dml/CPU 可用；CosyVoice2 的 speech_tokenizer 请求 CUDA 会回退到
# DML（非标准路径，部分算子数值不确定）。强制所有 onnx 会话走 CPU，取官方推荐的确定性、
# 可复现音色条件。补丁幂等，仅对构造 CosyVoice2 后产生的会话生效。
_ONNX_CPU_PATCHED = False


def _force_onnx_cpu_patch() -> None:
    global _ONNX_CPU_PATCHED
    if _ONNX_CPU_PATCHED:
        return
    try:
        import onnxruntime
    except ImportError as exc:
        raise RuntimeError(
            "未安装 onnxruntime（CosyVoice2 必需）。请先运行 "
            "`python \"语音合成 (CosyVoice)/src/install.py\"` 安装依赖。"
        ) from exc

    _orig_init = onnxruntime.InferenceSession.__init__

    def _cpu_init(self, path, sess_options=None, providers=None, **kw):
        return _orig_init(
            self, path, sess_options=sess_options,
            providers=["CPUExecutionProvider"], **kw,
        )

    onnxruntime.InferenceSession.__init__ = _cpu_init
    _ONNX_CPU_PATCHED = True


# 本机 Blackwell(sm_120) 上 fp16 推理失稳：同一句 fp16 与 bf16 输出波形相关性≈0，
# fp16 吐出 incoherent 乱码（用户听感“非人语/外语”）。bf16 数值范围与 fp32 一致，
# 走 bf16 autocast 既匹配 bf16 权重、又稳定正确。补丁幂等，仅影响本进程 cosyvoice 推理。
_BF16_AUTOCAST_PATCHED = False


def _force_bf16_autocast() -> None:
    global _BF16_AUTOCAST_PATCHED
    if _BF16_AUTOCAST_PATCHED:
        return
    import torch

    def _bf16(enabled: bool = True, dtype=None, **kw):
        # 覆盖 model.py 的 torch.cuda.amp.autocast(self.fp16)，统一改走 bf16。
        return torch.amp.autocast("cuda", enabled=bool(enabled), dtype=torch.bfloat16)

    torch.cuda.amp.autocast = _bf16
    _BF16_AUTOCAST_PATCHED = True


# transformers 5.x 的 prepare_padding_mask 把“单令牌”用户掩码右侧补 0，导致 past 位置被屏蔽，
# KV-cache 上下文坍塌 → LLM 退化为确定性的 2-循环、EOS 永不触发、输出 16s+ 无意义语音
# （用户听感“外语 + 呕偶欧”）。修复：forward_one_step 显式构造覆盖 past+current 的完整
# ones 掩码（等价于因果注意力，因 cache 中无未来令牌），让上下文完整参与注意力。
# 该补丁对 transformers 4.x 同样安全（全 1 掩码与因果掩码取交集仍为因果），幂等。
_MASK_PATCHED = False


def _patch_kv_cache_mask(cosy) -> None:
    global _MASK_PATCHED
    if _MASK_PATCHED:
        return
    try:
        # cosy.model.llm 是 Qwen2LM；其 .llm 属性才是持有 Qwen2ForCausalLM 与
        # forward_one_step 的 Qwen2Encoder。CosyVoice3 路径属性名一致，失败则跳过。
        encoder = cosy.model.llm.llm
    except AttributeError:
        logger.warning("CosyVoice 结构异常，跳过 KV-cache 掩码补丁")
        return

    import torch
    import types as _types

    _orig = encoder.forward_one_step

    def _patched(self, xs, masks, cache=None):
        cur = xs.shape[1]
        past_len = 0 if cache is None else int(getattr(cache, "_cosy_past_len", 0))
        total = past_len + cur
        # 完整长度 ones：覆盖 past+current 全部位置，上下文完整参与注意力
        am = torch.ones((1, total), device=xs.device, dtype=torch.bool)
        outs = self.model(
            inputs_embeds=xs,
            attention_mask=am,
            use_cache=True,
            past_key_values=cache,
            output_hidden_states=True,
            return_dict=True,
        )
        new_cache = outs.past_key_values
        # 把累计长度挂在 cache 对象上（不依赖 DynamicCache 内部 API，且可重入安全）
        setattr(new_cache, "_cosy_past_len", total)
        return outs.hidden_states[-1], new_cache

    encoder.forward_one_step = _types.MethodType(_patched, encoder)
    _MASK_PATCHED = True
    logger.info("已补丁 KV-cache 注意力掩码（修复 transformers 5.x 上下文坍塌）")


_BRICK_SRC = Path(__file__).resolve().parent


def _env_or(key: str, default: str) -> str:
    return os.getenv(key, default)


def _precision_mode() -> str:
    """cuda 下返回配置的精度（默认 bf16）；非 cuda 无 autocast fp16 概念。"""
    if _device() != "cuda":
        return "cpu"
    return _env_or("COSY_INFER_PRECISION", "bf16").lower()


# 内聚：默认权重/输出目录落在砖自身目录（语音合成 (CosyVoice)/cosyvoice_model），
# 不再指向项目共享的 Data/cosyvoice_model，使砖自包含、可被独立搬运。
# settings 是环境变量代理（__getattr__ 读 os.environ，未设置返回 None），
# 故不能用 `if settings is not None` 判断某项是否配置——它永远非 None 但值可能为 None。
# 统一用 _env_or：环境变量未设置时回退砖本地默认，砖自包含、可被独立搬运。
_BRICK_ROOT = _BRICK_SRC.parent


def _model_dir() -> str:
    return _env_or("COSY_MODEL_DIR", str(_BRICK_ROOT / "cosyvoice_model"))


def _output_dir() -> str:
    return _env_or("COSY_OUTPUT_DIR", str(_BRICK_ROOT / "cosyvoice_voices"))


def _device() -> str:
    return _env_or("COSY_INFER_DEVICE", "cuda")


def _seed_voice() -> str:
    return _env_or("COSY_DEFAULT_SEED_VOICE", "")


def _seed_text() -> str:
    return _env_or("COSY_DEFAULT_SEED_TEXT", "")


def _sample_text() -> str:
    return _env_or("COSY_DEFAULT_SAMPLE_TEXT", "你好，我是这个音色，很高兴为你服务。")


def _load_model():
    """懒加载 CosyVoice2 到本进程；未安装依赖时抛出明确错误（由调用方降级）。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    # 在构造 CosyVoice2（其内部会创建 onnx 会话）之前安装 CPU 补丁，
    # 确保 speech_tokenizer / campplus 走确定性 CPU 而非回退的 DML。
    _force_onnx_cpu_patch()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice2
    except ImportError as exc:
        raise RuntimeError(
            "未安装 cosyvoice（完整砖需将其装入运行 P.A.L.M 的环境）。"
            "请先运行 `python \"语音合成 (CosyVoice)/src/install.py\"` 安装依赖与权重。"
        ) from exc
    device = _device()
    prec = _precision_mode()
    # cuda 下默认 bf16：权重本就是 bf16，bf16 autocast 与之对齐且在本机稳定；
    # 本机 Blackwell 上 fp16 推理失稳（产出 incoherent 乱码），故默认不走 fp16。
    if prec == "bf16" and device == "cuda":
        _force_bf16_autocast()
    logger.info("加载 CosyVoice2 模型：%s（device=%s, precision=%s）", _model_dir(), device, prec)
    _ENGINE = CosyVoice2(
        _model_dir(),
        load_jit=False,
        load_trt=False,
        fp16=(device == "cuda"),
    )
    # 修复 transformers 5.x 的 KV-cache 上下文坍塌（必须在模型构造后、首次推理前打补丁）
    _patch_kv_cache_mask(_ENGINE)
    return _ENGINE


def _load_prompt_speech(path: str):
    from cosyvoice.utils.file_utils import load_wav

    return load_wav(path, 16000)


def create_voice(description: str = "", seed_audio: str = "",
                 seed_text: str = "", sample_text: str = "",
                 voice_id: str = "") -> dict:
    """造音：返回参考音频元数据（含 GSV 克隆所需路径与原文）。

    模式：有描述 → instruct2（基底音 + 自然语言风格）；无描述 → zero_shot（纯克隆基底）。
    """
    cosy = _load_model()
    seed = seed_audio or _seed_voice()
    if not seed or not os.path.isfile(seed):
        raise ValueError(
            "缺少 seed_audio（基底参考音频）；可在请求中提供，或配置 COSY_DEFAULT_SEED_VOICE。"
        )
    # CosyVoice2 的 inference_instruct2 / inference_zero_shot 接收的是文件路径，
    # 由 frontend 内部自行 load_wav，故此处直接传路径而非预加载的张量。
    prompt_speech = seed
    seed_text = seed_text or _seed_text()
    desc = (description or "").strip()
    sample = (sample_text or _sample_text()).strip()
    if not sample:
        raise ValueError("缺少 sample_text（参考音频朗读文案）。")

    if desc:
        gen = cosy.inference_instruct2(sample, desc, prompt_speech)
        mode = "instruct2"
    else:
        if not seed_text:
            raise ValueError("缺少 seed_text（基底原文）；纯克隆模式需要它。")
        gen = cosy.inference_zero_shot(sample, seed_text, prompt_speech)
        mode = "zero_shot"

    audio = next(gen)["tts_speech"]
    return _save_voice(cosy, audio, voice_id, mode, desc, sample)


def _save_voice(cosy, audio, voice_id: str, mode: str,
                description: str, sample_text: str) -> dict:
    out = Path(_output_dir()).resolve()
    out.mkdir(parents=True, exist_ok=True)
    vid = voice_id or _gen_voice_id(sample_text)
    wav_path = out / f"{vid}.wav"
    txt_path = out / f"{vid}.txt"
    json_path = out / f"{vid}.json"

    import soundfile as sf

    # torchaudio 2.11 保存同样路由到 torchcodec（需 ffmpeg），本机无 ffmpeg，改用 soundfile 写入。
    # audio 形状为 (channels, time)，soundfile 需 (time, channels)。
    audio_np = audio.cpu().numpy()
    data = audio_np if audio_np.ndim == 1 else audio_np.T
    sf.write(str(wav_path), data, getattr(cosy, "sample_rate", 24000))
    txt_path.write_text(sample_text, encoding="utf-8")

    meta = {
        "voice_id": vid,
        "mode": mode,
        "description": description,
        "sample_text": sample_text,
        "wav_path": str(wav_path),
        "text_path": str(txt_path),
        "gsv_refer_wav_path": str(wav_path),
        "gsv_prompt_text": sample_text,
        "gsv_prompt_language": "zh",
        "device": _device(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _gen_voice_id(sample_text: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    digest = abs(hash(sample_text)) % 100000
    return f"cosy_{stamp}_{digest}"


def list_voices() -> list[dict]:
    """扫描输出目录，列出已造音色元数据。"""
    out = Path(_output_dir())
    if not out.is_dir():
        return []
    voices: list[dict] = []
    for jf in sorted(glob.glob(str(out / "*.json"))):
        try:
            voices.append(json.loads(Path(jf).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return voices


def is_available() -> bool:
    """cosyvoice 是否已安装（仅探测导入，不加载模型）。"""
    try:
        import cosyvoice  # noqa: F401

        return True
    except ImportError:
        return False