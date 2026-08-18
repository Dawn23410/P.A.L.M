# 情绪分析桩：返回中性默认值。
def build_emotion_hint(text: str) -> str:
    return ""


def detect(text: str) -> dict:
    return {"valence": 0.0, "arousal": 0.0, "dominance": 0.0}


def extract_emotion_vector(text: str) -> list:
    return [0.0, 0.0, 0.0]
