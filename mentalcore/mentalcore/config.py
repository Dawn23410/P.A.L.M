"""微核心运行配置（环境驱动，零外部依赖）。

所有配置项均可用 MENTALCORE_ 前缀的环境变量覆盖，便于生产部署与密钥隔离。
**代码不内置任何 API key / 请求端点**：base_url / model / api_key 一律由
环境变量或 .env 提供（.env 已被 .gitignore 忽略，密钥只存在本地）。

供应商格式（已收窄）：仅 **openai 格式**（OpenAI 兼容协议）与 **mock**（离线）两种；
任意 OpenAI 兼容端点（官方 / Ollama / DeepSeek / Qwen / NoneLinear…）改
base_url + model + api_key 即可接入，无需改代码。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """微核心配置；mode=live 走真实 LLM，mode=mock 走离线回显（用于测试/演示）。"""

    # —— 运行模式 ——
    # 默认 mock（安全）：无配置时零 API 调用；在线需显式配置（.env / 环境变量 / 显式字典）
    mode: str = "mock"                 # live | mock
    # —— 模型供应商（OpenAI 兼容协议，可切 Ollama/DeepSeek/Qwen）——
    provider_mode: str = "openai"      # 仅 openai 格式（OpenAI 兼容端点：官方/Ollama/DeepSeek/Qwen 等）；mock 走离线
    base_url: str = ""                 # 必须由环境变量 / .env 提供（不内置任何端点）
    api_key: str = ""
    model: str = ""                    # 必须由环境变量 / .env 提供（不内置模型名）
    temperature: float | None = None
    max_tokens: int | None = None
    # —— 存储 ——
    storage_dir: str = "mentalcore_data/conversations"
    chroma_dir: str = "mentalcore_data/vector_memory"
    # —— 加密（SM4 国密，复用 palm crypto 原语）——
    crypto_enabled: bool = True
    master_key_hex: str = ""           # 32 位 hex；留空则生成本地主密钥并落盘
    master_key_file: str = "mentalcore_data/.master_key"
    # —— 情感识别 ——
    emotion_via_llm: bool = True       # False 则所有情绪回退中性 0,0,0
    # —— 外骨骼安全（Worker 护栏，方案1/4）——
    exo_profile: str = "strict"        # 护栏档位：hardline|strict|loose|ai|whitelist
    exo_rules_yaml: str = ""           # 护栏规则文件路径（空=内置默认，不改代码加规则）
    exo_ask_timeout: float = 60.0      # ask_user 阻塞等待秒数（宿主应答窗口）
    # —— 日志 ——
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, prefix: str = "MENTALCORE_") -> "Config":
        """加载 .env（仅缺失时注入）→ 环境变量覆盖（环境变量 > .env > 默认值）。

        端点 / 密钥 / 模型一律来自外部配置，代码不内置。
        """
        _load_env_file()
        cfg = cls()
        for key in (
            "mode", "provider_mode", "base_url", "api_key", "model",
            "temperature", "max_tokens", "storage_dir", "chroma_dir",
            "crypto_enabled", "master_key_hex", "master_key_file",
            "emotion_via_llm", "exo_profile", "exo_rules_yaml",
            "exo_ask_timeout", "log_level",
        ):
            env_val = os.environ.get(f"{prefix}{key.upper()}")
            if env_val is None:
                continue
            setattr(cfg, key, cls._coerce(env_val, cls.__dataclass_fields__[key].type))
        return cfg

    @staticmethod
    def _coerce(value: str, typ):
        if typ in (bool, "bool"):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if typ in (int, "int"):
            return int(value)
        if typ in (float, "float"):
            return float(value)
        return value

    def provider_ref(self):
        """构造 palm provider.stream_chat 所需的执行器引用（按属性访问，非 dict）。"""
        from types import SimpleNamespace
        return SimpleNamespace(
            base_url=self.base_url.rstrip("/"),
            api_key=self.api_key,
            mode=self.provider_mode,
        )


def _load_env_file() -> None:
    """零依赖读取 .env：仅当对应环境变量缺失时才注入，避免覆盖已设置的环境变量。

    查找顺序：项目根目录（包的上一级）的 .env，其次当前工作目录的 .env。
    """
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for dotenv in candidates:
        if not dotenv.is_file():
            continue
        try:
            for raw in dotenv.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except OSError:
            continue


def load_config(explicit: dict | None = None) -> Config:
    """优先用显式字典覆盖，其次环境变量 / .env，最后默认值。"""
    cfg = Config.from_env()
    if explicit:
        for k, v in explicit.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    return cfg
