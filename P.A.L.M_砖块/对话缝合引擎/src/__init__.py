"""【状态：已封砖 2026-08-14】对话缝合引擎砖块：角色对话的「检索 + 回调」缝合，

对外暴露：
- capability `stitch_api`：门面对象，供 chat/agent 经 interop 取用，默认以梦瑶角色卡
  产出拟人回复（stitch_api.reply / .status）。
- 工具 `stitch_chat`：agent/用户可直接调用的对话工具（经全局工具表注册）。

核心约束（与缝合引擎定位一致）：
- 默认 mock 模式：检索走 core.HybridRetriever（BM25 + 字 n-gram TF-IDF）内存索引，
  **零模型、零预构建向量、零下载**，开箱即用。垂直小模型（bge 嵌入 / 情感 BERT /
  改写 T5）仅在权重就位时自动升级，接口不变 —— 缺省全部 offline。
- 回复锚定真实手写语料（619 条梦瑶四要素对话），不生成事实，绝不胡说。
- 运行期绝对零联网。
"""
from __future__ import annotations

import logging

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared.tooling import Tool, ToolSpec, get_registry

from .engine import StitchEngine
from . import core, hub

_LOGGER = logging.getLogger(__name__)

# 角色 → 语料前缀（当前仅梦瑶；后续可扩展多角色）。
_CHARACTER_CORPUS_PREFIX = {
    "mengyao": "mengyao_hq_part",
}


class StitchApi:
    """缝合引擎门面：供其它砖经 capability 取用，避免直接 import 内部模块。"""

    def __init__(self, engine: StitchEngine):
        self.engine = engine

    def reply(self, query: str, history=None, character: str = "mengyao") -> dict:
        """生成角色回复。character 当前仅支持 mengyao（语料绑定）。"""
        if character not in _CHARACTER_CORPUS_PREFIX:
            return {
                "reply": f"暂不支持角色「{character}」，当前仅内置梦瑶。",
                "emotion": "calm", "recognized": False, "suggest_llm": False,
                "mode": self.engine.mode,
            }
        return self.engine.respond(query, history)

    def status(self) -> dict:
        return self.engine.status()


class StitchChatTool(Tool):
    """对外对话工具：以梦瑶角色卡缝合回复，零模型 mock 模式开箱即用。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="stitch_chat",
            description=(
                "与梦瑶（猫娘角色）自然对话。基于 619 条手写四要素语料的语义检索 + "
                "人格缝合，不调用大模型、不联网、不生成事实，回复锚定真实语料故不会胡说。"
                "适合老设备 / 零成本 / 离线场景下的拟人陪伴对话。情感与共情由轻量规则驱动。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "你对梦瑶说的话，例如「我好难过」「打雷好怕」「明天考试好慌」。",
                    },
                    "character": {
                        "type": "string",
                        "description": "角色标识，默认 mengyao（梦瑶）。",
                        "default": "mengyao",
                    },
                },
                "required": ["query"],
            },
            event_type="chat.stitch",
            permission="",
        )

    async def execute(self, query: str = "", character: str = "mengyao", **kwargs) -> str:
        if not query:
            return "参数缺失：stitch_chat 需要 query。"
        if _API is None or _ENGINE is None:
            return "缝合引擎未就绪（语料缺失），请检查砖内 corpus/ 目录。"
        try:
            result = _API.reply(query, history=None, character=character)
        except Exception as exc:  # fail-closed：引擎异常不拖垮调用方
            _LOGGER.warning("stitch_chat 执行异常: %s", exc, exc_info=True)
            return f"梦瑶暂时开小差了（{type(exc).__name__}），稍后再试喵～"
        return result.get("reply", "")


# ── 砖块注册 ──────────────────────────────────────────────────
_ENGINE: StitchEngine | None = None
_API: StitchApi | None = None

try:
    _ENGINE = StitchEngine()
    _API = StitchApi(_ENGINE)
    _status_note = f"就绪（模式={_ENGINE.mode}，语料={len(_ENGINE.records)} 条）"
except Exception as exc:  # 语料缺失等：砖仍注册，但引擎置空、工具降级提示
    _LOGGER.warning("缝合引擎初始化失败，砖以降级态注册: %s", exc, exc_info=True)
    _status_note = f"降级（引擎未就绪：{type(exc).__name__}）"


stitching_brick = Brick(
    manifest=BrickManifest(
        name="stitching",
        title="对话缝合引擎",
        description="角色对话的语义检索 + 人格回调缝合；默认 mock 模式（零模型零下载），"
                    "真实权重就位自动升级语义检索。",
        bus_type="ram",  # 状态化、易失的运行态对话引擎
    ),
    capabilities={
        "stitch_api": _API,
    },
)

registry.register(stitching_brick)
# 直接把 stitch_chat 注册进全局工具表（与导入顺序无关，agent 砖的 agent_tools 返回整个注册表）。
get_registry().register(StitchChatTool())

_LOGGER.info("对话缝合引擎砖已注册：%s", _status_note)