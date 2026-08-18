"""打断判定（规格 Task 3 第二/三级分流）：判断 STT 转录文本是否为打断意图。

分流规则（§5.2/§5.3）：
- 无文本（空/纯噪声）→ 假警报（VAD 误触发）
- 15 字以上长文本 → 正常陈述，非打断
- 1-14 字短文本 → 规则关键词优先；未命中时若 FastText 模型可用走模型，
  否则按"置信度不足兜底默认真"处理（§5.5：误打断代价远低于漏打断）

FastText 第三级需要标注训练数据（interrupt_train.txt），当前不可得；
模型路径留空即降级为规则+兜底，不阻断链路（加载失败同样降级）。
"""
from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger(__name__)

# §5.3 规则关键词（子串命中即可，如"停一下"含"停"）
_INTERRUPT_MARKERS = ("停一下", "等一下", "停", "等等", "闭嘴")
_FALSE_ALARM_MARKERS = ("没事", "算了", "没什么", "不用了", "继续", "你说")

# FastText 二分类模型路径；无训练数据时留空，走兜底不阻断。
FASTTEXT_MODEL_PATH = os.getenv("STT_FASTTEXT_MODEL", "")

_fasttext_model = None


def _load_fasttext() -> None:
    """惰性加载 FastText 模型；缺失/失败均降级（不阻断打断判定）。"""
    global _fasttext_model
    if not FASTTEXT_MODEL_PATH or not os.path.isfile(FASTTEXT_MODEL_PATH):
        return
    try:
        import fasttext
        _fasttext_model = fasttext.load_model(FASTTEXT_MODEL_PATH)
    except (ImportError, ValueError) as exc:
        _LOGGER.warning("打断 FastText 模型加载失败（降级为规则+兜底）: %s", exc)


def classify_interrupt(text: str) -> dict:
    """返回 {"is_interrupt", "confidence", "reason"}，供 TTS 播放层停止/恢复。"""
    t = (text or "").strip()
    if not t:
        return {"is_interrupt": False, "confidence": 0.9, "reason": "no_text"}
    if any(marker in t for marker in _INTERRUPT_MARKERS):
        return {"is_interrupt": True, "confidence": 0.95, "reason": "rule_interrupt"}
    if any(marker in t for marker in _FALSE_ALARM_MARKERS):
        return {"is_interrupt": False, "confidence": 0.9, "reason": "rule_false_alarm"}
    if len(t) >= 15:
        return {"is_interrupt": False, "confidence": 0.6, "reason": "long_text"}
    # 短文本规则未命中：FastText 可用则走模型，否则兜底默认真（§5.5）
    if _fasttext_model is not None:
        labels, probs = _fasttext_model.predict(t, k=1)
        is_interrupt = bool(labels) and labels[0].endswith("interrupt")
        confidence = float(probs[0]) if probs else 0.0
        if confidence < 0.6:
            # 模型低置信 → 安全兜底默认真（漏打断代价更高）
            return {"is_interrupt": True, "confidence": confidence, "reason": "model_low_conf"}
        return {"is_interrupt": is_interrupt, "confidence": confidence, "reason": "model"}
    return {"is_interrupt": True, "confidence": 0.5, "reason": "fallback_default"}


_load_fasttext()
