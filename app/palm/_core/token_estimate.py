def estimate_tokens(text: str) -> int:
    # 粗略估算：中文按字、英文按词。
    import re
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z0-9]+", text))
    return cn + en
