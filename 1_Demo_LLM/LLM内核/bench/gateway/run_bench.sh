#!/usr/bin/env bash
# 控制变量对照实验编排：一次调用跑完（WSL 每次会话都是冷启动，后台进程不跨会话存活）。
#
# 用法：  bash run_bench.sh [iters] [warmup]
# 产物：  bench/gateway/results/*.json   +   results/meta.json
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PY:-/home/24459/gwbench/bin/python}"
PORT="${PORT:-18080}"
ITERS="${1:-200}"
WARMUP="${2:-20}"
MAXTOK="${MAXTOK:-16}"
# 冷启动延迟：0 = 纯网关开销；>0 = 更贴近真实（模型耗时远大于网关差异）
ACK_MS="${ACK_MS:-0}"
CHUNK_MS="${CHUNK_MS:-0}"
RES="${RESDIR:-$HERE/results}"
MOCK="http://127.0.0.1:$PORT"
BIFROST_PORT=8080
PORTKEY_PORT=8787
export LITELLM_LOCAL_MODEL_COST_MAP=True

mkdir -p "$RES"
echo "== bench: iters=$ITERS warmup=$WARMUP ack=${ACK_MS}ms chunk=${CHUNK_MS}ms =="

cleanup() {
  docker rm -f bifrost-bench portkey-bench >/dev/null 2>&1
  pkill -f "mock_upstream.py --port $PORT" >/dev/null 2>&1
}
trap cleanup EXIT

cleanup
sleep 1

# ── 1. 确定性 mock 上游 ──
setsid nohup "$PY" "$HERE/mock_upstream.py" --port "$PORT" \
  --completion-tokens "$MAXTOK" --ack-delay-ms "$ACK_MS" \
  --chunk-delay-ms "$CHUNK_MS" >"$RES/mock.log" 2>&1 </dev/null &
for _ in $(seq 1 40); do
  curl -sf "$MOCK/v1/models" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -sf "$MOCK/v1/models" >/dev/null || { echo "FATAL: mock 未就绪"; exit 1; }
echo "-- mock ready @ $MOCK"

run_one() {   # run_one <label> <client> <base_url> [headers...]
  local label="$1" client="$2" url="$3"; shift 3
  local hdr=()
  for h in "$@"; do hdr+=(--header "$h"); done
  curl -sf "$MOCK/_reset" >/dev/null 2>&1
  "$PY" "$HERE/harness.py" --client "$client" --base-url "$url" \
      --model "${BENCH_MODEL:-bench-model}" --iters "$ITERS" --warmup "$WARMUP" \
      --label "$label" --out "$RES/$label.json" \
      --server-stats "$MOCK/_stats" "${hdr[@]}" 2>&1 | tail -2
}

# ── 2. 同语言四类实现（正面对照组）──
BENCH_MODEL=bench-model
run_one httpx_direct  httpx_direct "$MOCK/v1"
run_one palm_kernel   palm_kernel   "$MOCK/v1"
run_one litellm       litellm      "$MOCK/v1"
run_one openai_sdk    openai_sdk   "$MOCK/v1"

# ── 3. 自托管网关（跨语言参照组，单独成组）──
# 客户端固定用 httpx_direct：要量的是"网关"的净开销，不是 Python 框架的。
start_bifrost() {
  docker rm -f bifrost-bench >/dev/null 2>&1
  mkdir -p /tmp/bifrost-data
  docker run -d --name bifrost-bench --network host \
      -v /tmp/bifrost-data:/app/data maximhq/bifrost >/dev/null 2>&1 || return 1
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$BIFROST_PORT/metrics" >/dev/null 2>&1 && break
    sleep 0.5
  done
  # 把 mock 注册成 openai 供应商（management API，免配置文件路径猜谜）
  curl -s -X POST "http://127.0.0.1:$BIFROST_PORT/api/providers" \
      -H 'Content-Type: application/json' \
      -d "{\"provider\":\"openai\",\"network_config\":{\"base_url\":\"$MOCK/v1\"}}" >/dev/null 2>&1
  curl -s -X POST "http://127.0.0.1:$BIFROST_PORT/api/providers/openai/keys" \
      -H 'Content-Type: application/json' \
      -d '{"name":"bench","value":"dummy","models":["*"],"weight":1.0}' >/dev/null 2>&1
  # 两种路由形态都探一下，取可用的那条（探测信息走 stderr，别污染 stdout 的返回值）
  for path in /openai/v1 /v1; do
    code=$(curl -s -o /dev/null -w '%{http_code}' \
        -X POST "http://127.0.0.1:$BIFROST_PORT$path/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${BENCH_MODEL:-bench-model}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":4}")
    echo "   bifrost probe $path -> $code" >&2
    [ "$code" = "200" ] && { echo "$path"; return 0; }
  done
  return 1
}

start_portkey() {
  docker rm -f portkey-bench >/dev/null 2>&1
  docker run -d --name portkey-bench --network host \
      -e TRUSTED_CUSTOM_HOSTS="127.0.0.1,localhost" portkeyai/gateway >/dev/null 2>&1 || return 1
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORTKEY_PORT/v1/health" >/dev/null 2>&1 && break
    curl -sf "http://127.0.0.1:$PORTKEY_PORT/" >/dev/null 2>&1 && break
    sleep 0.5
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' \
      -X POST "http://127.0.0.1:$PORTKEY_PORT/v1/chat/completions" \
      -H 'Content-Type: application/json' -H 'x-portkey-provider: openai' \
      -H "x-portkey-custom-host: $MOCK/v1" -H 'Authorization: Bearer dummy' \
      -d "{\"model\":\"${BENCH_MODEL:-bench-model}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":4}")
  echo "   portkey probe /v1 -> $code" >&2
  [ "$code" = "200" ] && return 0
  return 1
}

BIFROST_PATH="$(start_bifrost)" && echo "-- bifrost ready @ :$BIFROST_PORT$BIFROST_PATH" \
  || echo "-- bifrost 不可用（已记录，不计入同语言对照）"
if [ -n "${BIFROST_PATH:-}" ]; then
  run_one bifrost httpx_direct "http://127.0.0.1:$BIFROST_PORT$BIFROST_PATH"
fi

if start_portkey; then
  echo "-- portkey ready @ :$PORTKEY_PORT"
  run_one portkey httpx_direct "http://127.0.0.1:$PORTKEY_PORT/v1" \
      "x-portkey-provider: openai" "x-portkey-custom-host: $MOCK/v1" \
      "Authorization: Bearer dummy"
else
  echo "-- portkey 不可用（已记录，不计入同语言对照）"
fi

# ── 3.5 基线复测：量化"整轮跑下来机器状态漂移了多少" ──
# 没有这一步，"palm 比基线快 1.9ms"这种负数就没法解释（是内核真的快，还是后跑占便宜？）
run_one baseline_retest httpx_direct "$MOCK/v1"

# ── 4. 元信息（谁在什么环境下跑的）──
"$PY" - "$RES/meta.json" "$ITERS" "$WARMUP" "$MAXTOK" "$ACK_MS" "$CHUNK_MS" <<'PYEOF'
import json, platform, subprocess, sys, importlib.metadata as md
out, iters, warmup, maxtok, ack, chunk = sys.argv[1:7]


def ver(pkg):
    try:
        return md.version(pkg)
    except Exception:
        return None


def img(name):
    try:
        return subprocess.run(["docker", "image", "inspect", name, "--format", "{{.Id}}"],
                              capture_output=True, text=True, timeout=20).stdout.strip()[:19]
    except Exception:
        return None


json.dump({
    "iters": int(iters), "warmup": int(warmup), "max_tokens": int(maxtok),
    "ack_delay_ms": float(ack), "chunk_delay_ms": float(chunk),
    "concurrency": 1, "transport": "HTTP/1.1 keep-alive",
    "python": platform.python_version(),
    "httpx": ver("httpx"), "litellm": ver("litellm"), "openai_sdk": ver("openai"),
    "platform": platform.platform(),
    "bifrost_image": img("maximhq/bifrost:latest"),
    "portkey_image": img("portkeyai/gateway:latest"),
}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF

echo "== done; 结果在 $RES =="
ls -1 "$RES"
