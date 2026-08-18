"""零依赖情绪正则检测器（主板共享设施）。

原位于 agent 砖内（agent/emotion_detector.py），因被 agent 与 memory 两砖
共用，按「零互导」契约下沉到主板 _shared 层：任何砖经
`from app.bricks._shared.emotion import ...` 取用，不再反向 import agent。

用纯正则识别中文用户消息中的情绪状态，供 Agent 注入情绪感知上下文。

设计约束：
- 纯标准库（re），零外部依赖，不引入 jieba / nltk 等分词库。
- **短语级匹配**，非单字级：避免「麻烦」误判为挫败、「开会」误判为开心。
  只有「好烦 / 心烦 / 烦死 / 烦人」等组合短语命中才算挫败；「开心」是完整词，
  不会匹配到「开会」。
- 情绪检测是**辅助信号**而非权威判断：注入 prompt 时用「提示」语气而非「指令」。
- 任何异常静默降级为「平静」，绝不抛错阻塞主流程。

返回结构示例：
    {
        "emotion": "挫败",
        "confidence": 0.78,
        "matched": ["烦死"],
        "intensity": "high"
    }
"""
from __future__ import annotations

import re

__all__ = ["detect", "build_emotion_hint", "CALM_RESULT", "extract_emotion_vector"]


# ── 情绪模式表（短语级，按情绪类型分组） ──
# 每条为正则字符串；finditer 命中即计入 matched。
# 刻意避免单字匹配：
#   ·「烦」只在「好烦 / 心烦 / 烦死 / 烦人 / 烦躁」等组合中出现才计挫败，
#     「麻烦」「繁琐」中的「烦」不会单独触发。
#   ·「开心」是完整词，「开会」不含该子串，不会误触。
_EMOTION_PATTERNS: dict[str, list[str]] = {
    "挫败": [
        r"烦死", r"好烦", r"心烦", r"烦人", r"烦躁", r"烦透",
        r"气死", r"好气", r"气人", r"生气", r"气炸", r"气透",
        r"愤怒", r"恼火", r"火大", r"抓狂", r"炸毛",
        r"受够了", r"受不了", r"烦得要命", r"气得要命",
        r"妈的", r"卧槽", r"我靠", r"真操蛋",
    ],
    "开心": [
        r"开心", r"高兴", r"快乐", r"兴奋", r"激动",
        r"太好了", r"好棒", r"棒极了", r"太棒了", r"超棒",
        r"哈哈+", r"嘿嘿", r"嘻嘻",
        r"超赞", r"太厉害", r"好厉害", r"牛啊", r"太牛",
        r"绝了", r"喜欢死", r"爱死",
    ],
    "焦虑": [
        r"担心", r"担忧", r"焦虑", r"害怕", r"恐惧",
        r"紧张", r"不安", r"心慌", r"忐忑", r"慌张",
        r"怎么办", r"完了完", r"糟了",
        r"怕死", r"吓死",
    ],
    "悲伤": [
        r"难过", r"伤心", r"悲伤", r"悲哀",
        r"郁闷", r"抑郁", r"低落", r"失落",
        r"想哭", r"哭了", r"哭死",
        r"绝望", r"崩溃", r"心碎",
        r"好累", r"心累", r"太累", r"累死", r"累瘫", r"疲惫", r"心力交瘁",
    ],
}

# 强度修饰词：出现则提升 intensity 等级（如「烦死了」中的「死了」）。
_INTENSITY_BOOSTERS: list[str] = [
    "死了", "透顶", "极", "非常", "特别", "超级", "爆", "要命",
    "不行", "坏了", "炸了",
]

# 预编译：每类情绪一个合并正则（用非捕获组拼接，避免 group 干扰 finditer 取词）
_COMPILED: dict[str, re.Pattern] = {
    name: re.compile("|".join(f"(?:{p})" for p in pats))
    for name, pats in _EMOTION_PATTERNS.items()
}
_BOOSTER_RE = re.compile("|".join(f"(?:{p})" for p in _INTENSITY_BOOSTERS))
# 重复符号也算情绪宣泄强度加成：3 个以上「哈」、2 个以上感叹号
_REPEAT_LAUGH_RE = re.compile(r"(哈){3,}")
_REPEAT_BANG_RE = re.compile(r"[！!]{2,}")


def _detect_one(text: str, name: str) -> list[str]:
    """对单类情绪执行正则，返回去重后的命中短语列表（保留首次出现顺序）。"""
    pat = _COMPILED[name]
    found: list[str] = []
    seen: set[str] = set()
    for m in pat.finditer(text):
        word = m.group(0)
        if word not in seen:
            seen.add(word)
            found.append(word)
    return found


def _calm() -> dict:
    """平静兜底结果。confidence 取低值（平静是默认态，不确定性较高）。"""
    return {
        "emotion": "平静",
        "confidence": 0.3,
        "matched": [],
        "intensity": "low",
    }


CALM_RESULT: dict = _calm()


# ── 中国人情绪效价-唤醒映射表 ──
# 基于中文语境修正（vs 西方常模）：
# 1. 儒家文化情绪表达偏内敛，唤醒基线整体低于西方常模
# 2. "挫败"含无奈语义，效价不如纯愤怒极端（-0.5 vs 西方 anger -0.7）
# 3. "悲伤"偏沉默内敛，唤醒低（中国"哀而不伤"文化）
# 4. intensity 修正：high 档提升唤醒，low 档降低唤醒
_EMOTION_VA_MAP: dict[str, dict[str, float]] = {
    "开心": {
        "valence": 0.7,
        "arousal_high": 0.7,
        "arousal_mid": 0.5,
        "arousal_low": 0.3,
    },
    "挫败": {
        "valence": -0.5,
        "arousal_high": 0.85,
        "arousal_mid": 0.6,
        "arousal_low": 0.4,
    },
    "焦虑": {
        "valence": -0.4,
        "arousal_high": 0.75,
        "arousal_mid": 0.5,
        "arousal_low": 0.3,
    },
    "悲伤": {
        "valence": -0.7,
        "arousal_high": 0.45,
        "arousal_mid": 0.25,
        "arousal_low": 0.15,
    },
    "平静": {
        "valence": 0.0,
        "arousal_high": 0.1,
        "arousal_mid": 0.1,
        "arousal_low": 0.05,
    },
}


def extract_emotion_vector(text: str) -> tuple[float, float, float]:
    """从文本提取情绪向量 (valence, arousal, confidence)。

    调用 detect() 获取情绪标签和强度，查表映射为连续数值。
    任何异常降级为 (0.0, 0.0, 0.0)（无情绪标记，向后兼容）。

    返回:
        (valence, arousal, confidence)
        valence ∈ [-1, +1], arousal ∈ [0, 1], confidence ∈ [0, 1]
    """
    try:
        result = detect(text)
        emotion = result.get("emotion", "平静")
        intensity = result.get("intensity", "low")
        confidence = result.get("confidence", 0.3)

        va = _EMOTION_VA_MAP.get(emotion)
        if va is None:
            return (0.0, 0.0, 0.0)

        arousal_key = f"arousal_{intensity}" if f"arousal_{intensity}" in va else "arousal_low"
        return (va["valence"], va[arousal_key], confidence)
    except Exception:
        return (0.0, 0.0, 0.0)


def detect(text: str) -> dict:
    """检测文本情绪，返回结构化结果。

    返回:
        {
            "emotion": "挫败" | "开心" | "焦虑" | "悲伤" | "平静",
            "confidence": float,   # 0.0~1.0
            "matched": list[str],  # 命中的情绪短语
            "intensity": "high" | "mid" | "low"
        }

    任何异常静默降级为「平静」，绝不抛出。
    """
    if not text or not isinstance(text, str):
        return _calm()

    try:
        scores: dict[str, list[str]] = {}
        for name in _EMOTION_PATTERNS:
            matched = _detect_one(text, name)
            if matched:
                scores[name] = matched

        if not scores:
            return _calm()

        # 取命中短语最多的情绪为主情绪（并列时按 _EMOTION_PATTERNS 声明顺序取先）
        primary_name, matched = max(
            scores.items(), key=lambda kv: len(kv[1])
        )
        match_count = len(matched)

        # 强度判断：命中数 + 修饰词 + 重复符号
        booster_hits = len(set(_BOOSTER_RE.findall(text)))
        has_repeat = bool(_REPEAT_LAUGH_RE.search(text)) or bool(_REPEAT_BANG_RE.search(text))

        if match_count >= 3 or (match_count >= 1 and booster_hits >= 1):
            intensity = "high"
            confidence = min(0.95, 0.65 + 0.08 * match_count + 0.05 * booster_hits)
        elif match_count >= 2 or has_repeat:
            intensity = "mid"
            confidence = min(0.85, 0.55 + 0.1 * match_count)
        else:
            intensity = "low"
            confidence = 0.5

        return {
            "emotion": primary_name,
            "confidence": round(confidence, 2),
            "matched": matched,
            "intensity": intensity,
        }
    except Exception:  # noqa: BLE001  任何异常静默降级，绝不污染主流程
        return _calm()


def build_emotion_hint(result: dict | None) -> str:
    """把检测结果转为注入 prompt 的提示文本。

    - 平静情绪返回空串（不注入，避免噪声）。
    - 用「提示」语气而非「指令」，强调情绪检测是辅助信号、非权威判断。

    返回的文本已带前导换行，便于直接拼接到 system prompt 末尾。
    """
    if not result:
        return ""
    try:
        emotion = result.get("emotion", "平静")
        if emotion == "平静":
            return ""
        intensity = result.get("intensity", "low")
        matched = result.get("matched", []) or []
        intensity_label = {
            "high": "高强度", "mid": "中强度", "low": "轻度"
        }.get(intensity, "轻度")
        matched_str = (
            "、".join(f"'{w}'" for w in matched[:3])
            if matched else "无明显情绪词"
        )
        # 按情绪极性给出不同的应对提示（仍是「建议」语气，非「指令」）
        if emotion == "开心":
            advice = "可适度共情、分享这份积极情绪，但不要刻意迎合"
        else:
            advice = "如需安抚则温和安抚，但不要过度解读或反复提及情绪"
        return (
            "\n\n## 🎯 用户情绪感知（辅助信号，非权威判断）\n"
            f"[当前用户情绪状态：{emotion}（{intensity_label}，匹配到{matched_str}）—— "
            f"请在回应中适度体现情绪感知。{advice}，把它当作参考而非定论]"
        )
    except Exception:  # noqa: BLE001
        return ""
