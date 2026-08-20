"""prompt 注入缓存探针：Boss / Worker 各 N 轮（真实 API 调用）。

目标：
- 用项目真实 prompt 构建（Worker=build_worker_prompt 归档模板 / Boss=心智魔方五面装配）。
- 每轮追加一轮历史（变动内容），固定 system 不动（固定内容）。
- --window>0 时只保留最近 K 轮历史（滑动窗口截断，压输入斜率）。
- 统计每轮：输入 token（API usage.prompt_tokens）、缓存命中/未命中 token、
  固定/变动占比（按字符启发式拆分后等比换算到 API 数值）。
- 输出 CSV + 控制台表格。
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

CONF_PATH = r"C:\Users\24459\Desktop\可用API.json"
ROUNDS = 20
MODEL = "GLM-4.5-Flash-nothink"
OUT_CSV = r"C:\Users\24459\Desktop\P.A.L.M\mentalcore\prompt缓存轨迹_20260820.csv"
OUT_JSON = r"C:\Users\24459\Desktop\P.A.L.M\mentalcore\prompt缓存轨迹_20260820.json"


def load_conf():
    with open(CONF_PATH, encoding="utf-8") as f:
        return json.load(f)


def est_tokens(text: str) -> int:
    """启发式 token 估算（GLM 系）：中文≈0.85/字，ASCII 字母数字≈0.28/字符。仅用于占比拆分。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_n = max(0, len(text) - cjk)
    return max(1, int(cjk * 0.85 + ascii_n * 0.28))


def chat_once(conf, messages, retries=4):
    url = conf["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + conf["api_key"],
               "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages,
               "temperature": 0.3, "max_tokens": 96, "stream": False}
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content, data.get("usage", {})
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}: {exc.read()[:150]!r}"
            if exc.code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = repr(exc)
            time.sleep(1)
    raise RuntimeError(f"调用失败：{last_err}")


def cache_fields(usage: dict):
    """OpenAI/DeepSeek 两种缓存字段兼容提取。"""
    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    if hit is None and isinstance(usage.get("prompt_tokens_details"), dict):
        hit = usage["prompt_tokens_details"].get("cached_tokens")
        miss = usage["prompt_tokens_details"].get("uncached_tokens")
    return hit, miss


def build_prompts():
    """用项目真实装配路径构建固定 system。"""
    from mentalcore import build_exo
    from mentalcore.config import Config
    from mentalcore import MentalCore
    from mentalcore.persona_card import default_persona
    from mentalcore.crypto_provider import CryptoProvider
    from mentalcore.faces.storage import StorageFace

    # Worker：外骨骼真实路径
    cube = build_exo(Config(mode="mock"))
    wcore = cube.core
    wcore.memory.add(
        "experience", "整理文件时优先按项目名建子目录；同名文件保留最新版本",
        keywords=["整理", "文件"])
    worker_goal = "帮我整理桌面上的项目文件并生成一份摘要"
    worker_ctx = "用户把文件散落在桌面，希望归类后给清单"
    worker_system = wcore._build_prompt(goal=worker_goal, context=worker_ctx, history=[])

    # Boss：心智魔方五面装配 + Worker 进展注入
    base = r"C:\Users\24459\Desktop\P.A.L.M\mentalcore\mentalcore_data\probe_tmp"
    os.makedirs(base, exist_ok=True)
    cfg = Config(mode="mock", storage_dir=base + "/conv", chroma_dir=base + "/vm",
                 master_key_file=base + "/.key")
    crypto = CryptoProvider(enabled=False, key_file=cfg.master_key_file)
    storage = StorageFace(path=cfg.storage_dir, crypto=crypto, semantic_memory=None)
    boss = MentalCore(persona=default_persona(), llm=None, crypto=crypto,
                      semantic_memory=None, storage=storage,
                      emotion_via_llm=False, persist=False)
    modules = boss._collect_modules("你好呀，帮我看看后台任务进展")
    external = ("【后台 Worker 进展】\nWorker 任务：整理桌面项目文件\n"
                "已执行 2 步（进行中）\n  步骤1 [list_directory] 桌面 3 个文件\n"
                "  步骤2 [read_file] notes.md 已读取")
    boss_system = boss._assemble(modules, external)
    return worker_system, boss_system, wcore, worker_goal, worker_ctx


def run_worker_compressed(wcore, goal, ctx, window=6):
    """压缩模式：每轮用真实 _build_prompt（摘要式压缩）重建提示，模拟真实 Worker 发送。"""
    conf = load_conf()
    hist: list[tuple] = []
    rows = []
    for k in range(1, ROUNDS + 1):
        prompt = wcore._build_prompt(goal=goal, context=ctx, history=hist)
        reply, usage = chat_once(
            conf, [{"role": "system", "content": ""},
                   {"role": "user", "content": prompt}])
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        hit, miss = cache_fields(usage)
        obs = (f"第 {k} 步观测：list_directory 返回 3 个文件"
               "（a.py/notes.md/backup.zip），请继续整理并汇报下一步。")
        rows.append({
            "side": "Worker", "round": k, "window": window, "mode": "compressed",
            "input_tokens": prompt_tokens,
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cache_hit": hit, "cache_miss": miss,
            "fixed_est": est_tokens(prompt), "var_est": 0,
            "fixed_tokens": prompt_tokens, "var_tokens": 0,
            "history_turns": len(hist),
        })
        print(f"[Worker-压缩] 第{k:02d}轮 输入={prompt_tokens} 命中={hit} "
              f"轨迹{len(hist)}步", flush=True)
        hist.append(("list_directory", obs))
        time.sleep(0.3)
    return rows


def run_side(name, system, user_gen, window=0):
    """跑 N 轮：固定 system + 每轮追加一轮历史（window>0 时滑动截断）；返回逐轮记录。"""
    conf = load_conf()
    history = []
    rows = []
    for k in range(1, ROUNDS + 1):
        user_msg = user_gen(k)
        hist = history if window <= 0 else history[-2 * window:]
        messages = [{"role": "system", "content": system}] + hist + [
            {"role": "user", "content": user_msg}]
        reply, usage = chat_once(conf, messages)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        hit, miss = cache_fields(usage)
        # 固定/变动拆分：按字符启发式占比换算到 API 数值
        fixed_est = est_tokens(system)
        var_text = "\n".join(m["content"] for m in hist) + "\n" + user_msg
        var_est = est_tokens(var_text)
        total_est = fixed_est + var_est
        fixed_api = int(prompt_tokens * fixed_est / total_est) if total_est else 0
        var_api = max(0, prompt_tokens - fixed_api)
        rows.append({
            "side": name, "round": k, "window": window,
            "input_tokens": prompt_tokens,
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cache_hit": hit, "cache_miss": miss,
            "fixed_est": fixed_est, "var_est": var_est,
            "fixed_tokens": fixed_api, "var_tokens": var_api,
            "history_turns": len(hist) // 2,
        })
        print(f"[{name}] 第{k:02d}轮 输入={prompt_tokens} 命中={hit} "
              f"固定≈{fixed_api} 变动≈{var_api} (窗内历史{len(hist)//2}轮)", flush=True)
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": reply[:80]})
        time.sleep(0.3)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=0, help="历史滑动窗口轮数（0=不限）")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--sides", default="both", choices=["both", "worker", "boss"])
    ap.add_argument("--compressed", action="store_true",
                    help="Worker 用真实 _build_prompt 摘要式压缩重建提示")
    args = ap.parse_args()
    global ROUNDS
    ROUNDS = args.rounds
    suffix = "_comp" if args.compressed else f"_win{args.window}" if args.window > 0 else ""
    global OUT_CSV, OUT_JSON
    OUT_CSV = OUT_CSV.replace(".csv", f"{suffix}.csv")
    OUT_JSON = OUT_JSON.replace(".json", f"{suffix}.json")

    worker_system, boss_system, wcore, worker_goal, worker_ctx = build_prompts()
    all_rows = []
    if args.compressed:
        all_rows += run_worker_compressed(wcore, worker_goal, worker_ctx,
                                          window=args.window or 6)
    else:
        if args.sides in ("both", "worker"):
            all_rows += run_side("Worker", worker_system,
                                 lambda k: f"第 {k} 步观测：list_directory 返回 3 个文件（a.py/notes.md/backup.zip），请继续整理并汇报下一步。",
                                 window=args.window)
            time.sleep(1)
        if args.sides in ("both", "boss"):
            all_rows += run_side("Boss", boss_system,
                                 lambda k: f"第 {k} 轮闲聊：今天海边的风真舒服，你那边呢？顺便看看后台任务进展。",
                                 window=args.window)

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        import csv
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print("CSV:", OUT_CSV)
    print("JSON:", OUT_JSON)
    print("DONE")


if __name__ == "__main__":
    main()
