"""声卡扩展卡（PCIe）：像简易主板一样管理内部四个音频引擎组件。

对外仅暴露「声卡」一块砖；声卡内部加载并持有 声纹识别 / 语音识别 /
语音合成(GPT-SoVITS) / 语音合成(CosyVoice) 四个引擎组件。

对外接口收敛为 **5 通道协议模型**（取代原先 6 个命名能力）：
- 传入 soundcard_ingest：入站总线，承载控制/数据/外部事件，内部按类型路由。
- 传出 soundcard_drain：出站总线，抽取待发消息（心跳信号 + 加载数据包 + 出站数据）。
- 心跳 soundcard_heartbeat：统一 UUID 存活信号（就绪/异常两态），后台周期写入传出队列；
  消费者没收到信号即视为「没活着」。
- 控制 soundcard_control：控制码 + 解码器单入口（原 6 能力的语义全部折叠进控制码）。
- 数据 soundcard_data：与控制面分离的数据载荷通道（音频/文本等双向传递）。

首次加载主动向主板推送「加载数据包」（启动引导 + 控制码表 + 内容），由传出总线承载，
主板后续接入时 drain 即可收到。

组件砖经 palm_sdk 的 load_brick_package 加载（导入即注册进全局 registry），
声卡经 registry.get(组件名) 取句柄并转发控制，自身不重复注册组件能力键、零键冲突。
"""
from __future__ import annotations

import inspect
import logging
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks.loader import load_brick_package
from palm_sdk.security import require_api_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/soundcard", tags=["soundcard"])

# 心跳周期（秒）：声卡以此频率向外传递存活信号。
HEARTBEAT_INTERVAL = 5.0

# 内部组件：registry 键 -> 砖目录名（位于本卡目录内，由声卡自管理）。
_COMPONENTS = {
    "speaker": "声纹识别",
    "stt": "语音识别",
    "tts_sovits": "语音合成 (GPT-SoVITS)",
    "cosyvoice": "语音合成 (CosyVoice)",
}


class SoundCard:
    """简易主板式容器：加载并管理内部音频引擎组件，统一对外 5 通道控制面。"""

    def __init__(self) -> None:
        self._here = Path(__file__).resolve().parent
        self.components: dict[str, Brick] = {}
        self._enabled: set[str] = set()
        self._load_errors: dict[str, str] = {}
        # 统一存活信号：卡级唯一 UUID + 两态（就绪/异常）。
        self._uuid = str(uuid.uuid4())
        self._state = "ready"
        self._last_beat = 0.0
        self._outbox: list[dict] = []  # 传出队列：心跳信号 + 加载包 + 出站数据
        self._inbox: list[dict] = []   # 传入暂存（非控制/数据的未知消息）
        self._data: object = None      # 数据通道当前载荷
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._load_all()
        # 任一组件加载失败 -> 整卡进入异常态（心跳会向外广播异常）。
        if self._load_errors:
            self._state = "abnormal"
        self._beat()            # 立刻发一帧初始心跳，确保加载即存活可见
        self._push_load_packet()  # 首次加载：主动向主板推送加载数据包
        self._start_heartbeat()    # 启动后台周期心跳

    def _load_all(self) -> None:
        """加载全部内部组件，单组件失败不拖垮整卡。"""
        for key, folder in _COMPONENTS.items():
            src = self._here.parent / folder / "src"
            pkg = f"palm_bricks._card_soundcard_{key}"
            try:
                load_brick_package(src, pkg)  # 触发组件注册
                brick = registry.get(key)
                if brick is None:
                    raise RuntimeError("组件导入未注册（可能处于依赖降级态）")
                self.components[key] = brick
                self._enabled.add(key)
            except Exception as exc:  # noqa: BLE001  单组件失败不拖垮整卡
                self._load_errors[key] = f"{type(exc).__name__}: {exc}"
                logger.warning("声卡组件加载失败 %s: %s", key, exc)

    # ---- 心跳通道 ----

    def _beat(self, state: str | None = None) -> dict:
        """生成一帧存活信号并写入传出队列。state 缺省沿用当前态。"""
        with self._lock:
            if state:
                self._state = state
            signal = {"uuid": self._uuid, "state": self._state, "ts": time.time()}
            self._last_beat = signal["ts"]
            self._outbox.append({"type": "heartbeat", "signal": signal})
            return signal

    def heartbeat_signal(self) -> dict:
        """返回当前心跳信号（消费者也可经传出队列 drain 到周期流）。"""
        with self._lock:
            return {"uuid": self._uuid, "state": self._state, "ts": self._last_beat}

    def _start_heartbeat(self) -> None:
        """后台守护线程：周期把存活信号推入传出队列，实现「向外传递」。"""
        def loop() -> None:
            while not self._stop.is_set():
                self._beat()
                self._stop.wait(HEARTBEAT_INTERVAL)
        threading.Thread(target=loop, daemon=True).start()

    # ---- 首次加载：加载数据包（主动推送主板）----

    def _push_load_packet(self) -> None:
        """构造并向传出队列推送加载数据包：启动引导 + 控制码 + 内容。"""
        packet = {
            "type": "load_packet",
            "uuid": self._uuid,
            "boot": {  # 启动引导：主板据此完成卡槽接入与生命周期管理
                "card": "声卡",
                "bus": "pcie",
                "isolation": "inproc",
                "components": _COMPONENTS,
                "heartbeat_interval": HEARTBEAT_INTERVAL,
            },
            "control_codes": self.schema(),  # 控制码全集：主板据此生成路由表
            "content": self.status()["components"],  # 内容：各引擎就绪/能力明细
        }
        with self._lock:
            self._outbox.append(packet)
        logger.info("声卡已推送加载数据包（UUID=%s，主板 drain 即可收到）", self._uuid)

    # ---- 传出 / 传入 总线 ----

    def drain(self) -> list[dict]:
        """传出：抽取并清空出站队列（心跳信号 + 加载数据包 + 出站数据）。"""
        with self._lock:
            items = list(self._outbox)
            self._outbox.clear()
        return items

    def ingest(self, envelope: dict) -> dict:
        """传入：入站总线。按消息类型路由——控制走解码器，数据走数据通道。"""
        if not isinstance(envelope, dict):
            raise ValueError("envelope 须为 dict")
        etype = envelope.get("type")
        if etype == "control":
            return self.dispatch(envelope.get("code", ""), envelope.get("params") or {})
        if etype == "data":
            return {"ok": True, "data": self.data(envelope.get("payload"))}
        # 其余未知类型原样暂存，供后续扩展消费。
        with self._lock:
            self._inbox.append(envelope)
        return {"ok": True, "stored": True}

    # ---- 控制通道：控制码 + 解码器 ----

    def schema(self) -> dict:
        """返回控制码全集（即加载数据包里的 control_codes，供主板/外部发现）。"""
        return {
            "status": "聚合各组件 加载/启用/就绪 状态",
            "power.on": "整卡启用全部组件",
            "power.off": "整卡停用全部组件",
            "enable": "启用整卡（可带 .组件 指定单个）",
            "enable.<comp>": "启用指定组件",
            "disable": "停用整卡（可带 .组件 指定单个）",
            "disable.<comp>": "停用指定组件",
            "command.<comp>.<action>": "把动作路由到指定引擎的对应能力",
            "actions": "列出各组件可用能力",
            "actions.<comp>": "列出指定组件可用能力",
            "schema": "返回本控制码表",
        }

    def dispatch(self, code: str, params: dict | None) -> object:
        """解码器：按 code 命名空间把控制码分发到内部实现。"""
        parts = code.split(".")
        head = parts[0]
        params = params or {}
        if head == "status":
            return self.status()
        if head == "schema":
            return self.schema()
        if head == "power":
            return self.power(parts[1] if len(parts) > 1 else "on")
        if head == "enable":
            return self.enable(parts[1] if len(parts) > 1 else None)
        if head == "disable":
            return self.disable(parts[1] if len(parts) > 1 else None)
        if head == "actions":
            return self.list_actions(parts[1] if len(parts) > 1 else None)
        if head == "command":
            if len(parts) < 3:
                raise ValueError("command 控制码格式须为 command.<comp>.<action>")
            return self.command(parts[1], parts[2], **params)
        raise KeyError(f"未知控制码: {code}")

    def control(self, code: str, params: dict | None = None) -> object:
        """控制通道单入口（与传入 control 消息同构）。"""
        return self.dispatch(code, params)

    # ---- 数据通道 ----

    def data(self, payload: object = None) -> object:
        """数据面：双向载荷传递，与控制面分离。提供载荷即写入并随传出广播。"""
        if payload is not None:
            with self._lock:
                self._data = payload
                self._outbox.append({"type": "data", "payload": payload})
        return self._data

    # ---- 内部实现（卡级 / 模块级，经控制码可达）----

    def power(self, state: str) -> dict:
        """整卡电源：on 启用全部组件 / off 停用全部组件。"""
        if state not in ("on", "off"):
            raise ValueError("state 须为 on/off")
        self._enabled = set(self.components) if state == "on" else set()
        return self.status()

    def enable(self, component: str | None = None) -> dict:
        """启用整卡或指定组件。component=None 表示整卡。"""
        if component is None:
            self._enabled = set(self.components)
        elif component in self.components:
            self._enabled.add(component)
        else:
            raise KeyError(f"未知组件: {component}")
        return self.status()

    def disable(self, component: str | None = None) -> dict:
        """停用整卡或指定组件。停用的组件不再接受 soundcard_command 下发。"""
        if component is None:
            self._enabled = set()
        elif component in self.components:
            self._enabled.discard(component)
        else:
            raise KeyError(f"未知组件: {component}")
        return self.status()

    def command(self, component: str, action: str, **params):
        """将动作路由到指定内部组件的对应能力（颗粒度直达各模块）。"""
        brick = self.components.get(component)
        if brick is None:
            raise KeyError(
                f"未知或不可用组件: {component}（{self._load_errors.get(component, '')}）"
            )
        if component not in self._enabled:
            raise RuntimeError(f"组件 {component} 已停用，先 enable 再下发指令")
        fn = brick.capabilities.get(action)
        if fn is None:
            avail = ", ".join(sorted(brick.capabilities))
            raise KeyError(f"组件 {component} 无能力 {action}；可用: {avail}")
        return fn(**params)

    def list_actions(self, component: str | None = None) -> dict:
        """列出组件可用能力，供外部发现颗粒度控制点。"""
        if component is None:
            return {k: sorted(v.capabilities) for k, v in self.components.items()}
        brick = self.components.get(component)
        if brick is None:
            raise KeyError(f"未知组件: {component}")
        return {component: sorted(brick.capabilities)}

    # ---- 状态聚合 ----

    def _comp_status(self, key: str) -> dict:
        brick = self.components.get(key)
        if brick is None:
            return {
                "key": key, "title": _COMPONENTS.get(key, key),
                "loaded": False, "enabled": False, "available": False,
                "error": self._load_errors.get(key),
            }
        title = getattr(brick.manifest, "title", key)
        avail = None
        cap = brick.capabilities.get("is_available") or brick.capabilities.get(
            f"is_{key}_available"
        )
        if cap is not None:
            try:
                result = cap()
                if inspect.iscoroutine(result):
                    # 同步上下文无法安全驱动协程，丢弃以免 "never awaited" 告警，标记未知。
                    result.close()
                    avail = None
                else:
                    avail = bool(result)
            except Exception:  # noqa: BLE001  探测异常视为未就绪
                avail = False
        return {
            "key": key, "title": title,
            "loaded": True,
            "enabled": key in self._enabled,
            "available": avail,
            "actions": sorted(brick.capabilities),
        }

    def status(self) -> dict:
        comps = [self._comp_status(k) for k in _COMPONENTS]
        return {
            "card": "声卡", "bus": "pcie", "uuid": self._uuid, "state": self._state,
            "component_count": len(comps),
            "enabled_count": sum(1 for c in comps if c.get("enabled")),
            "ready_count": sum(1 for c in comps if c.get("available")),
            "components": comps,
        }


card = SoundCard()

brick = Brick(
    manifest=BrickManifest(
        name="soundcard",
        title="声卡",
        description=(
            "PCIe 扩展卡：像简易主板一样管理 声纹识别 / 语音识别 / "
            "语音合成(GPT-SoVITS) / 语音合成(CosyVoice) 四个音频引擎组件。"
            "对外仅暴露本砖，内部加载并持有各引擎，统一提供 5 通道协议面："
            "传入/传出 总线、心跳（统一 UUID 存活信号）、控制（控制码+解码器）、数据（双向载荷）。"
        ),
        is_core=False,
        bus_type="pcie",
        can_accept_files=False,
        isolation="inproc",
        endpoint="inproc://",
    ),
    router=router,
    capabilities={
        # 5 通道协议面
        "soundcard_ingest": card.ingest,      # 传入：入站总线
        "soundcard_drain": card.drain,        # 传出：出站总线
        "soundcard_heartbeat": card.heartbeat_signal,  # 心跳：统一 UUID 存活信号
        "soundcard_control": card.control,    # 控制：控制码 + 解码器
        "soundcard_data": card.data,          # 数据：双向载荷通道
    },
)
registry.register(brick)


# ---- HTTP 面（与 5 通道 capability 同构）----


@router.post("/ingest", dependencies=[Depends(require_api_token)])
async def soundcard_ingest_api(payload: dict):
    """传入：入站消息 {type: control|data|..., ...}。"""
    try:
        return {"ok": True, "result": card.ingest(payload)}
    except Exception as exc:  # noqa: BLE001  转发层错误原样回传
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/drain", dependencies=[Depends(require_api_token)])
async def soundcard_drain_api():
    """传出：抽取待发消息（心跳信号 + 加载数据包 + 出站数据）。"""
    return card.drain()


@router.get("/heartbeat", dependencies=[Depends(require_api_token)])
async def soundcard_heartbeat_api():
    """心跳：返回当前统一 UUID 存活信号（就绪/异常）。"""
    return card.heartbeat_signal()


@router.post("/control", dependencies=[Depends(require_api_token)])
async def soundcard_control_api(payload: dict):
    """控制：{code: 'power.on'|'command.stt.list_keywords'|..., params: {...}}。"""
    try:
        return {"ok": True, "result": card.control(payload.get("code", ""), payload.get("params"))}
    except Exception as exc:  # noqa: BLE001  转发层错误原样回传
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/data", dependencies=[Depends(require_api_token)])
async def soundcard_data_api(payload: dict):
    """数据：{payload: ...} 写入并随传出广播；无 payload 则返回当前载荷。"""
    return {"ok": True, "data": card.data(payload.get("payload"))}
