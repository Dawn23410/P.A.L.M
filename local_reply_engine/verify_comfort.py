# -*- coding: utf-8 -*-
"""安慰补洞泛化验证：语料外变异句 ×3 抽，检查兜底/错配/伪影"""
import sys, io, re, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine

# 与 full_regression.py 同源的伪影断言（避免 import 副作用）
BAD_PATTERNS = [
    (r"本喵", "自称残留"),
    (r"(喵|呀|呜|哼|嘛|哦|啦|呢)\1", "叠尾双粒子"),
    (r"）[呀喵呜哼嘛哦啦]", "括号外贴尾"),
    (r"[？！][喵呀呜哼嘛哦啦]", "问叹号后贴尾"),
    (r"\{[^}]*\}", "槽位语法泄漏"),
    (r"<你>", "记忆变量未展开"),
    (r"\|?\d+；|\|\d", "槽位权重泄漏"),
    (r"[a-zA-Z]{4,}", "异常英文残留"),
    (r"，，|。。", "标点重复"),
    (r"^\s*$", "空回复"),
]
WHITELIST_EN = ("carry", "hello", "emo", "LLM", "deadline", "hi", "party", "fish", "offer")

def check_artifacts(text):
    problems = []
    for pat, name in BAD_PATTERNS:
        for m in re.finditer(pat, text):
            frag = m.group()
            if name.startswith("异常英文") and any(w in frag for w in WHITELIST_EN):
                continue
            if name == "自称残留" and "小本本喵" in text[max(0, m.start() - 2):m.end() + 1]:
                continue
            if name == "叠尾双粒子" and frag in ("哼哼",):
                continue
            if name == "括号外贴尾" and text[m.start():m.start() + 2] in ("）哼", "）喵"):
                continue
            if name == "问叹号后贴尾" and (frag in ("？哼", "？喵。")
                    or (frag == "？喵" and text[m.end():m.end() + 1] == "。")):
                continue
            if name == "标点重复" and frag == "！！":
                continue
            problems.append((name, frag))
    return problems

CASES = [
    "给我一点安慰", "安慰一下我嘛", "安慰安慰我", "谁来安慰我一下",
    "抱抱我吧", "想要一个抱抱", "求抱抱",
    "哄哄我呀", "你就不能哄哄我吗", "我心情很差，安慰我", "今天被骂了，安慰我",
]
BAD = ("没聊过", "换个我会的", "连上云端")
random.seed(49)
eng = StitchEngine(semantic=True)
fail = 0
for q in CASES:
    fb = 0
    arts = []
    for i in range(3):
        r = eng.respond(q)
        rep = r.get("reply") or ""
        if r.get("suggest_llm") or any(b in rep for b in BAD):
            fb += 1
        arts += check_artifacts(rep)
    tag = "ok" if fb == 0 and not arts else "FAIL"
    if tag == "FAIL":
        fail += 1
        print(f"[{tag}] {q}  fallback={fb}/3 artifacts={arts[:2]}")
print("comfort generalization:", "PASS" if fail == 0 else f"FAIL ({fail})")
