# -*- coding: utf-8 -*-
"""槽位组合引擎 · 关键词注入（把一条回复拆成 x+y+z 槽位，加权概率选组合）。

语料模板语法（写在 a_raw 里，与普通记录共存，随机化池照常工作）：
  {选项1|权重;选项2|权重;...}   槽位组：`;` 分隔选项，`|权重` 可省（默认 1）。
  选项文本~标签1,标签2          `~` 后接情绪标签（happy/sad/calm/neutral/any…），
                               当前情绪不在标签集 → 该选项权重×0.15（软惩罚不断杀，
                               保组合空间不塌缩）。
  <你> / <名字>                记忆变量：用户报名过 → 注入真名；否则回退"你"。

概率模型（模仿 LLM 的加权采样，非 argmax）：
  p_i ∝ base_i × mood_i × recency_i × name_i
  - argmax 会让组合恒定（死板）；均匀随机浪费概率信息。加权采样 = LLM 式
    top-p 近似：大概率选项更常出现，小概率选项保留惊喜。
  - recency：近 6 轮用过的组合文本 ×0.35，驱动槽位轮转。
  - name：选项含 <你> 且已知用户名 → ×1.3（有记忆可用时优先个性化）。
组合数：3 槽 × 4 选项 ≈ 64 组合/模板，远超静态多份改写。

fail-closed：解析异常/空组 → 确定性取首个选项，绝不抛错到检索主链路。
"""
import re

_GROUP_RE = re.compile(r"\{([^{}]*)\}")

# 情绪完全不在标签集时的软惩罚（不是 0：保组合空间，只降"跑错情绪"的概率）
_MOOD_MISMATCH_PENALTY = 0.15
_RECENCY_PENALTY = 0.35
_NAME_BONUS = 1.3


def _parse_options(group):
    """解析槽位组 → [(text, weight, mood_tags)]。空组返回 []。"""
    opts = []
    for part in group.split(";"):
        part = part.strip()
        if not part:
            continue
        text, weight, tags = part, 1.0, set()
        if "|" in part:
            text, _, w = part.rpartition("|")
            try:
                weight = float(w)
            except ValueError:
                text = part  # 权重字段非法 → 整段当文本，fail-closed
        if "~" in text:
            text, _, tag_str = text.partition("~")
            tags = {t.strip() for t in tag_str.split(",") if t.strip()}
        text = text.strip()
        if text:
            opts.append((text, max(weight, 0.0), tags))
    return opts


def _weighted_pick(scored):
    """按累计权重采样（p_i ∝ w_i）。全零权重 → 退化取首个。"""
    total = sum(w for _, w in scored)
    if total <= 0:
        return scored[0][0] if scored else ""
    r = random_uniform(total)
    for text, w in scored:
        r -= w
        if r <= 0:
            return text
    return scored[-1][0]


def random_uniform(total):
    """[0, total) 均匀采样。独立成函数便于测试替换/桩掉随机性。"""
    import random
    return random.random() * total


def fill(template, ctx):
    """填充模板。ctx: {name, emotion, recent}。

    返回成品文本；模板无槽位组时仅做变量替换后原样返回（None 表示无需处理）。
    """
    name = (ctx or {}).get("name")
    emotion = (ctx or {}).get("emotion") or "neutral"
    recent = (ctx or {}).get("recent") or set()

    def sub_vars(t):
        return t.replace("<你>", name or "你").replace("<名字>", name or "你")

    if "{" not in template:
        return sub_vars(template) if "<你>" in template or "<名字>" in template else None

    def pick(match):
        opts = _parse_options(match.group(1))
        if not opts:
            return ""
        scored = []
        for text, w, tags in opts:
            if tags and "any" not in tags and emotion not in tags:
                w *= _MOOD_MISMATCH_PENALTY
            filled = sub_vars(text)
            if filled in recent:
                w *= _RECENCY_PENALTY
            if ("<你>" in text or "<名字>" in text) and name:
                w *= _NAME_BONUS
            scored.append((filled, w))
        return _weighted_pick(scored)

    try:
        return _GROUP_RE.sub(pick, template)
    except Exception:  # fail-closed：任何解析异常都不打断主链路
        return _GROUP_RE.sub(lambda m: (_parse_options(m.group(1)) or [("", 0, set())])[0][0], template)
