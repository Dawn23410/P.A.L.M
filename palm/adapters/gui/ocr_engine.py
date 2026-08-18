"""OCR 引擎自适应分层：默认 onnxruntime（纯 CPU 并行），GPU 挡走 DML，单线程挡降并行度。

集中管理 OCR 推理引擎的生命周期（懒加载单例 + 启动预热），
供 desktop_control.ocr_boxes 与 GUI 世界模型链路复用。

默认策略（见 OCRSettings）：enable_gpu=False → onnxruntime 纯 CPU 多线程（CPU 并行）；
挡位开关：enable_gpu=True 切 GPU(DML) 挡；cpu_intra_threads=1 切单线程挡；
openvino 因 import 时污染 rapidocr_onnxruntime 全局类，仅作兜底且永远后置（见 get_ocr_engine 防污染重排）。

所有可调参数收口到 OCRSettings，后期动态管理器只需调用 set_ocr_settings 覆盖并触发引擎重建。
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field

from PIL import Image

_LOGGER = logging.getLogger(__name__)

_OCR_ENGINE = None
_OCR_ENGINE_NAME = ""


@dataclass
class OCRSettings:
    """OCR 引擎可调参数。默认值：CPU 并行（GPU 关、线程并行开）、不启角度分类。

    后期动态管理只需覆盖字段（set_ocr_settings），引擎会在下次获取时按新值重建。
    保留挡位开关：GPU 挡 enable_gpu=True；单线程挡 enable_gpu=False + cpu_intra_threads=1。
    """
    engine_order: list[str] = field(
        default_factory=lambda: ["dml", "openvino", "onnxruntime"])
    enable_gpu: bool = False                # 默认 CPU 并行；True 即切 GPU(DML) 挡
    cpu_intra_threads: int = 0              # 0=ORT 默认（并行开）；1=单线程挡
    cpu_inter_threads: int = 0
    use_angle_cls: bool = False
    use_mobile_models: bool = False         # 轻量模型（兼容旧 PALM_OCR_MOBILE 环境变量）


_SETTINGS = OCRSettings()
_SETTINGS_LOCK = threading.Lock()


def _dml_available() -> bool:
    """本机 onnxruntime 是否带 DmlExecutionProvider。"""
    try:
        import onnxruntime as _ort
        return "DmlExecutionProvider" in _ort.get_available_providers()
    except Exception:
        return False


def _install_session_patch(use_dml: bool):
    """按 _SETTINGS 给 OrtInferSession 打补丁（DML + 线程数），返回原 init 以便还原。

    统一 DML 注入与线程控制，避免各引擎重复 monkey-patch；建完引擎即还原，互不污染。
    """
    try:
        from onnxruntime import (
            InferenceSession, SessionOptions, GraphOptimizationLevel)
        from rapidocr_onnxruntime.utils import OrtInferSession
    except Exception:
        return None
    orig = OrtInferSession.__init__
    intra = _SETTINGS.cpu_intra_threads
    inter = _SETTINGS.cpu_inter_threads

    def _patched(self, config):
        so = SessionOptions()
        so.log_severity_level = 4
        so.enable_cpu_mem_arena = False
        so.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
        if intra:
            so.intra_op_num_threads = intra
            so.inter_op_num_threads = inter or 1
        providers = []
        if use_dml and _dml_available():
            providers.append("DmlExecutionProvider")
        providers.append("CPUExecutionProvider")
        self._verify_model(config["model_path"])
        self.session = InferenceSession(
            config["model_path"], sess_options=so, providers=providers)

    OrtInferSession.__init__ = _patched
    return orig


def _warmup_engine(engine) -> None:
    """空图预热一次：触发 DML shader / OpenVINO 图编译，使其不再计入首次真实 OCR 耗时。"""
    try:
        warm_path = os.path.join(tempfile.gettempdir(), "palm_ocr_warmup.png")
        Image.new("RGB", (64, 64), (255, 255, 255)).save(warm_path)
        engine(warm_path)
    except Exception:
        pass


def _find_mobile_models() -> dict | None:
    """检测 rapidocr models 目录是否存在 mobile 轻量模型，返回其 kwargs 覆盖项。"""
    try:
        import glob
        import rapidocr_onnxruntime
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        models_dir = os.path.join(pkg_dir, "models")
        det = glob.glob(os.path.join(models_dir, "*mobile*det*.onnx"))
        rec = glob.glob(os.path.join(models_dir, "*mobile*rec*.onnx"))
        if not (det and rec):
            return None
        override = {"det_model_path": det[0], "rec_model_path": rec[0]}
        keys = glob.glob(os.path.join(models_dir, "*mobile*rec*.txt"))
        if keys:
            override["rec_keys_path"] = keys[0]
        return override
    except Exception:
        return None


def _init_ort_engine(use_dml: bool):
    """onnxruntime 引擎：use_dml=True 注入 DML(GPU)，False 纯 CPU；按 _SETTINGS 控制线程/模型。"""
    if use_dml and not _dml_available():
        return None
    try:
        from rapidocr_onnxruntime.utils import OrtInferSession
    except Exception:
        return None
    orig = _install_session_patch(use_dml)
    if orig is None:
        return None
    try:
        kwargs = {"use_angle_cls": _SETTINGS.use_angle_cls}
        if _SETTINGS.use_mobile_models or os.environ.get("PALM_OCR_MOBILE") == "1":
            mobile = _find_mobile_models()
            if mobile:
                kwargs.update(mobile)
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR(**kwargs)
    except Exception:
        return None
    finally:
        OrtInferSession.__init__ = orig


def _init_openvino_engine():
    """OpenVINO（纯 CPU，C++ 内核）；为旧版 rapidocr 注入 openvino.runtime 兼容层。"""
    try:
        import sys as _sys
        import types as _types
        import importlib.abc as _abc
        import importlib.machinery as _mach
        import openvino
        if not hasattr(openvino, "runtime"):
            _mod = _types.ModuleType("openvino.runtime")
            _mod.Core = openvino.Core
            _sys.modules["openvino.runtime"] = _mod

            class _Finder(_abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "openvino.runtime":
                        return _mach.ModuleSpec(fullname, _mach.SourceFileLoader(fullname, ""), is_package=False)
                    return None

            _sys.meta_path.insert(0, _Finder())
        from rapidocr_openvino import RapidOCR
        return RapidOCR()
    except Exception:
        return None


_ENGINE_BUILDERS = {
    "dml": lambda: _init_ort_engine(use_dml=True),
    "openvino": _init_openvino_engine,
    "onnxruntime": lambda: _init_ort_engine(use_dml=False),
}


def get_ocr_engine():
    """懒加载 OCR 引擎（全局复用）：按 _SETTINGS.engine_order 逐级降级。

    防污染重排：rapidocr_openvino 在 import 时会把 rapidocr_onnxruntime 的全局
    TextDetector 等类替换成 openvino 定制版（依赖 pre_process 字段），导致之后
    再构建纯 onnxruntime/dml 引擎必然 KeyError。故无论 engine_order 如何写，
    永远让 onnxruntime/dml 排在 openvino 之前，openvino 仅作最后兜底。
    """
    global _OCR_ENGINE, _OCR_ENGINE_NAME
    if _OCR_ENGINE is None:
        raw = _SETTINGS.engine_order
        if _SETTINGS.enable_gpu:
            chain = ([e for e in raw if e == "dml"]
                     + [e for e in raw if e not in ("dml", "openvino")]
                     + [e for e in raw if e == "openvino"])
        else:
            chain = ([e for e in raw if e == "onnxruntime"]
                     + [e for e in raw if e not in ("dml", "onnxruntime", "openvino")]
                     + [e for e in raw if e == "openvino"])
        for name in chain:
            init = _ENGINE_BUILDERS.get(name)
            if init is None:
                continue
            engine = init()
            if engine is not None:
                _OCR_ENGINE = engine
                _OCR_ENGINE_NAME = name
                _warmup_engine(engine)
                _LOGGER.info("OCR 引擎初始化: %s", name)
                break
        if _OCR_ENGINE is None:
            _OCR_ENGINE = False
    return _OCR_ENGINE if _OCR_ENGINE is not False else None


def get_ocr_engine_name() -> str:
    """返回实际生效的引擎名（dml/openvino/onnxruntime/空）。"""
    return _OCR_ENGINE_NAME


def get_ocr_settings() -> OCRSettings:
    """返回当前 OCR 设置（动态管理器读取入口）。"""
    return _SETTINGS


def set_ocr_settings(**overrides) -> None:
    """动态覆盖 OCR 设置并使缓存引擎失效（下次 get_ocr_engine 按新值重建）。"""
    with _SETTINGS_LOCK:
        for key, value in overrides.items():
            if hasattr(_SETTINGS, key):
                setattr(_SETTINGS, key, value)
        _invalidate_engine()


def _invalidate_engine() -> None:
    """清空引擎缓存，强制下次获取时按当前 _SETTINGS 重建。"""
    global _OCR_ENGINE, _OCR_ENGINE_NAME
    _OCR_ENGINE = None
    _OCR_ENGINE_NAME = ""
