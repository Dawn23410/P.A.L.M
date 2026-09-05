"""可用 API 快照：实测端点模型，生成 JSON 清单。

输出：环境变量 PALM_API_JSON，缺省 ~/Desktop/可用API.json（含端点/key/默认模型/各模型可用性/TTFB/推荐）
用法：python api_snapshot.py
"""
import json
import os
import time

import httpx

from mentalcore.config import load_config

MODELS = [
    "GLM-4.7-Flash", "GLM-4.5-Flash", "GLM-4.5-Flash-nothink",
    "DeepSeek-R1-0528-Qwen3-8B:free", "Qwen3-8B:free", "Qwen3-8B-nothink:free",
    "GLM-4-9B-0414:free", "GLM-Z1-9B-0414:free", "qwen2.5-1.5b-instruct",
    "GLM-4-Flash", "internlm2_5-7b-chat:free", "xunfei-spark-lite",
]

# 输出路径：优先环境变量 PALM_API_JSON，否则回退到当前用户桌面（跨机器可移植）。
OUT = os.environ.get("PALM_API_JSON", os.path.expanduser("~/Desktop/可用API.json"))


def probe(client, url, headers, model):
    """非流式可用性 + 是否推理型。"""
    try:
        r = client.post(f"{url}/chat/completions",
                        json={"model": model,
                              "messages": [{"role": "user", "content": "你好"}],
                              "max_tokens": 20},
                        headers=headers, timeout=30.0)
        if r.status_code != 200:
            return {"ok": False, "http": r.status_code}
        body = r.json()
        msg = (body.get("choices") or [{}])[0].get("message") or {}
        usage = body.get("usage") or {}
        rk = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        return {"ok": True, "thinking": bool(msg.get("reasoning")
                                             or msg.get("reasoning_content") or rk)}
    except Exception as exc:
        return {"ok": False, "err": repr(exc)[:60]}


def ttfb_of(client, url, headers, model):
    """流式首 token 延迟。"""
    try:
        t0 = time.time()
        with client.stream("POST", f"{url}/chat/completions",
                           json={"model": model, "stream": True,
                                 "messages": [{"role": "user", "content": "只回复一个字：好"}],
                                 "max_tokens": 20},
                           headers=headers, timeout=40.0) as r:
            if r.status_code != 200:
                return None
            for line in r.iter_lines():
                if line.strip() and "content" in line:
                    return round(time.time() - t0, 2)
        return None
    except Exception:
        return None


def main():
    cfg = load_config()
    url = cfg.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    client = httpx.Client(timeout=45.0)

    models = []
    for m in MODELS:
        time.sleep(1.0)
        p = probe(client, url, headers, m)
        entry = {"name": m, **p}
        if p.get("ok"):
            ttfb = ttfb_of(client, url, headers, m)
            entry["ttfb_s"] = ttfb
            time.sleep(1.0)
        models.append(entry)
        print(f"{m:<30} ok={p.get('ok')} http={p.get('http', '-')} "
              f"thinking={p.get('thinking', '-')} ttfb={entry.get('ttfb_s')}s")

    recommended = [m["name"] for m in models
                   if m.get("ok") and not m.get("thinking")]
    snapshot = {
        "provider": "nonelinear",
        "format": "openai",  # OpenAI 兼容格式
        "base_url": cfg.base_url,
        "api_key": cfg.api_key,
        "default_model": cfg.model,
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "recommended_models": recommended,
        "models": models,
        "notes": "推荐模型须非推理型（限死不开深度思考）；GLM-4-Flash 虽快但不遵守 ||DATA|| 数据区协议，慎用。",
    }
    json.dump(snapshot, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"已生成: {OUT}")


if __name__ == "__main__":
    main()
