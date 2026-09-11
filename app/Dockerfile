# P.A.L.M 微内核运行镜像 —— Linux 友好，为跨平台扩展预留
# 说明：
# - 核心微内核（palm/mentalcore/llm/security/memory/tool/plan/gui/sandbox）为纯 Python，
#   torch/vosk/chromadb/playwright 等重型依赖全部“懒加载 + 降级”，缺则不影响内核装配。
# - speech/ 是 vendored 第三方（GPT-SoVITS/vosk/cosyvoice）且含 Windows 内嵌 python，
#   不烤入镜像；通过 docker-compose 卷挂载或独立服务接入（见 docker-compose.yml）。
# - gui/adapters_gui 依赖 uiautomation/pyautogui（Windows 桌面自动化），容器内默认不启用，
#   bootstrap/app.py 已用 try/except 降级，缺失不影响装配。

# ── 阶段 1：构建期（仅编译/装包）──
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 系统级依赖：ffmpeg（音频/视频转码，GSV 与 vosk 需要）、portaudio（sounddevice 录音）、
# 编译工具（部分纯 Python 轮子需要）、git（部分依赖从 git 安装）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        portaudio19-dev \
        build-essential \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/palm

# 先装声明依赖 + 可选核心依赖（穷尽式一次性装，避免重复层）。
# torch 用 CPU 版以减小体积；若要 GPU 改为 cu121 版torch。
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install "pydantic>=2.10" && \
    pip install "httpx>=0.27" "numpy>=1.24" "numpy<2" && \
    pip install "vosk>=0.3.45" "sounddevice>=0.4" && \
    pip install "chromadb>=0.4" "python-dotenv>=1.0" && \
    pip install "torch>=2.2" --index-url https://download.pytorch.org/whl/cpu && \
    pip install "gmssl>=3.2"

# ── 阶段 2：运行期 ──
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 区域/货币：默认 CNY，红涨绿跌已在可视化层遵循；此处仅设 locale 与编码
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    # 默认离线优先：内核自身 fail-closed，联网需显式开启
    PALM_OFFLINE=${PALM_OFFLINE:-0} \
    # 数据/缓存目录（容器内统一落这里，便于卷挂载）
    PALM_DATA=/data \
    PALM_API_JSON=/data/可用API.json

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        portaudio19-dev \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 palm && useradd -u 1000 -g 1000 -m -s /bin/bash palm

WORKDIR /opt/palm

# 从构建期复制已装好的 site-packages（仅必要的重依赖），避免重复安装。
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# 复制项目源码（speech/ 由 .dockerignore 排除，避免 17GB 烤入；按需卷挂载）。
COPY . /opt/palm

# 入口脚本：默认以非 root 运行；支持“命令透传”（docker run palm <任意入口脚本>）。
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER palm
WORKDIR /opt/palm

# 默认端口：GSV TTS (:9880)、预留 Web/API 端口。
EXPOSE 9880 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-c", "import palm.bootstrap.app as a; a.build_app(); print('P.A.L.M 内核装配完成，容器就绪')"]
