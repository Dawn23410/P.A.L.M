#!/usr/bin/env bash
# P.A.L.M 容器入口：保证数据目录、装配内核，并透传任意命令。
# 用法：
#   docker run --rm palm-image                      # 仅装配内核并打印就绪
#   docker run --rm palm-image python tests/xxx.py  # 运行任意入口脚本
#   docker run --rm palm-image bash                # 进入交互 shell
set -euo pipefail

# 确保数据目录存在（卷挂载点）；非 root 用户需可写。
mkdir -p "${PALM_DATA:-/data}" 2>/dev/null || true

# 可选：若容器内需要 GSV，可由环境变量 PALM_GSV_SRC 指向卷内源码后启动其服务。
# 默认仅在存在时启动（前提：已 mount speech 卷并安装好 torch 环境）。
if [ "${PALM_ENABLE_GSV:-0}" = "1" ] && [ -n "${PALM_GSV_SRC:-}" ]; then
    echo "[entrypoint] GSV 已启用，源码位于 ${PALM_GSV_SRC}"
fi

# 透传：若带参数则用参数，否则用镜像默认 CMD。
if [ "$#" -ge 1 ]; then
    exec "$@"
fi
echo "P.A.L.M 容器就绪；使用 'docker run palm-image <命令>' 运行具体任务。"
