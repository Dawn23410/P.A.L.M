"""通用控制芯片：可装到任意砖上的标准控制 IC。

五通道协议（对外能力）：
- 控制 control / request：双向同步控制面。control 处理下行（主板→芯片），
  request 发起上行（芯片→主板）；两条独立通路，可同时各飞一条、互不阻塞。
- 传入 ingest：入站总线，按 type 路由（control→解码，data→数据通道）。
- 传出 drain：出站总线，抽取心跳信号 + 加载数据包 + 出站数据。
- 心跳 heartbeat_signal：统一 UUID 存活信号（就绪/异常），后台周期广播；没收即没活着。
- 数据 data：与控制面分离的字符串载荷双向通道（任意内容先序列化进字符串再发）。

控制码：8 位十六进制 = 32-bit，三段 ns(4bit) | target(12bit) | action(16bit)。
- ns=0 芯片标准协议（状态/模式/心跳/复位/版本）
- ns=1 宿主直连能力（开发模式注册 / 绑定模式映射既有接口）
- ns=2 容器卡组件能力（target=组件号，action=组件内动作；由 component_resolver 二次分发）

双模式：
- 开发模式：@control_code_route(0x1...) 装饰类方法，芯片构造时自动注册。
- 绑定模式：chip.bind(0x1..., 既有函数) 把控制码映射到已有接口，零改动。

本模块纯标准库，不依赖 palm.py / fastapi，可独立导入与单元测试。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Optional

# 命名空间（32-bit 控制码的高 4 位）
NS_STD = 0    # 芯片标准协议
NS_HOST = 1   # 宿主直连能力
NS_COMP = 2   # 容器卡组件能力

# 标准协议控制码（ns=0, target=0）
STD_STATUS = 0x00000001
STD_SCHEMA = 0x00000002
STD_HEARTBEAT = 0x00000003
STD_SHUTDOWN = 0x00000004
STD_RELEASE_PERF = 0x00000005
STD_RESUME = 0x00000006
STD_RESET = 0x0000000F
STD_VERSION = 0x00000010


def _split_code(code: int) -> tuple[int, int, int]:
    """32-bit 控制码拆成 (ns, target, action) 三段。"""
    code = int(code) & 0xFFFFFFFF
    return (code >> 28) & 0xF, (code >> 16) & 0xFFF, code & 0xFFFF


def _to_int(code: Any) -> int:
    """控制码归一为 int：支持 '0x1A' / '1A' / 0x1A / 26。"""
    if isinstance(code, str):
        return int(code, 16)
    return int(code)


def control_code_route(code: Any) -> Callable:
    """开发模式装饰器：标记类方法为某控制码处理函数，芯片构造时经 adopt 自动注册。"""
    cid = _to_int(code)

    def deco(fn: Callable) -> Callable:
        fn._control_code = cid  # 标记，供芯片 adopt 扫描
        return fn

    return deco


class ControlChip:
    """通用控制芯片：五通道 + 32-bit 控制码路由 + 双模式（开发/绑定）。"""

    def __init__(self, host: Any = None, *, name: str = "chip", bus: str = "pcie",
                 isolation: str = "inproc", heartbeat_interval: float = 5.0,
                 component_resolver: Optional[Callable] = None,
                 board_endpoint: Optional[Callable] = None,
                 version: str = "0.1.0") -> None:
        self.host = host
        self.name = name
        self.bus = bus
        self.isolation = isolation
        self.heartbeat_interval = heartbeat_interval
        self.version = version
        self._component_resolver = component_resolver
        self._board_endpoint = board_endpoint

        self.uuid = uuid.uuid4().hex
        self._state = "ready"
        self._abnormal_reason: Optional[str] = None
        self._last_beat = 0.0
        self._outbox: list[dict] = []
        self._inbox: list[dict] = []
        self._data: Any = None
        self._registry: dict[int, tuple[str, Callable]] = {}

        self._state_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._down_lock = threading.Lock()  # 下行（被控）处理锁
        self._up_lock = threading.Lock()    # 上行（主控）发起锁：与下行独立，互不阻塞
        self._stop = threading.Event()
        self._paused = False          # 释放性能时为 True：心跳广播暂停但实例仍响应 control

        if host is not None:
            self.adopt(host)
        self._beat()                 # 加载即存活可见
        self._push_load_packet()     # 首次加载主动推送加载数据包
        self._call_host("on_loaded")  # 宿主可选初始化钩子
        self._start_heartbeat()      # 后台周期心跳

    # ---- 双模式注册 ----

    def adopt(self, host: Any) -> None:
        """扫描宿主类上被 @control_code_route 标记的方法并注册（开发模式）。"""
        for attr in (getattr(host, n) for n in dir(host)):
            if callable(attr) and hasattr(attr, "_control_code"):
                self.register(getattr(attr, "_control_code"), attr)

    def register(self, code: Any, fn: Callable) -> Callable:
        """开发模式：把一个函数注册为某控制码的处理函数。"""
        self._registry[_to_int(code)] = ("dev", fn)
        return fn

    def bind(self, code: Any, fn: Callable) -> Callable:
        """绑定模式：把控制码映射到已有接口（零改动老接口），优先于开发注册。"""
        self._registry[_to_int(code)] = ("bound", fn)
        return fn

    def _call_host(self, name: str, *args) -> None:
        """调用宿主可选钩子（on_loaded / on_release_perf / on_shutdown）。

        钩子不存在或抛异常均静默忽略——标准状态机不依赖宿主动作，
        重型砖（如 GSV）可实现钩子接管真实生命周期（暂停/关停子进程）。
        """
        host = self.host
        if host is None:
            return
        fn = getattr(host, name, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception:  # noqa: BLE001  宿主钩子异常不影响控制面
                pass

    # ---- 控制通道：双向同步 ----

    def control(self, code: Any, params: Any = None) -> Any:
        """被控入口（下行：主板→芯片）。同步阻塞处理并返回结果，异常向上抛。"""
        with self._down_lock:
            return self._dispatch(_to_int(code), params)

    def request(self, code: Any, params: Any = None) -> Any:
        """主控入口（上行：芯片→主板）。同步阻塞等主板响应；未配端点则失败关门。"""
        if self._board_endpoint is None:
            raise RuntimeError("芯片未配置主板上行端点 board_endpoint")
        with self._up_lock:
            return self._board_endpoint(_to_int(code), params or {})

    def _dispatch(self, code: int, params: Any) -> Any:
        """控制码解析 + 三段路由。"""
        ns, target, action = _split_code(code)
        if ns == NS_STD:
            return self._standard(code, params)
        if ns == NS_HOST:
            entry = self._registry.get(code)
            if entry is None:
                raise KeyError(f"未注册控制码: 0x{code:08X}")
            return entry[1](params or {})
        if ns == NS_COMP:
            if self._component_resolver is None:
                raise NotImplementedError("ns=2 组件寻址需提供 component_resolver")
            return self._component_resolver(target, action, params or {})
        raise KeyError(f"未分配命名空间 ns={ns}")

    def _standard(self, code: int, params: Any) -> Any:
        """ns=0 芯片标准协议。"""
        if code == STD_STATUS:
            return self.status()
        if code == STD_SCHEMA:
            return self.schema()
        if code == STD_HEARTBEAT:
            return self.heartbeat_signal()
        if code == STD_SHUTDOWN:
            self.shutdown()
            return {"ok": True, "shutdown": True}
        if code == STD_RELEASE_PERF:
            self.release_perf()
            return {"ok": True, "released": True}
        if code == STD_RESUME:
            self.resume()
            return {"ok": True, "resumed": True}
        if code == STD_VERSION:
            return {"version": self.version}
        if code == STD_RESET:
            with self._queue_lock:
                self._outbox.clear()
            return {"ok": True, "reset": "outbox"}
        raise KeyError(f"未知标准控制码: 0x{code:08X}")

    # ---- 心跳通道 ----

    def _beat(self) -> dict:
        with self._state_lock:
            signal = {"uuid": self.uuid, "state": self._state, "ts": time.time()}
            self._last_beat = signal["ts"]
        with self._queue_lock:
            self._outbox.append({"type": "heartbeat", "signal": signal})
        return signal

    def heartbeat_signal(self) -> dict:
        with self._state_lock:
            return {"uuid": self.uuid, "state": self._state, "ts": self._last_beat}

    def mark_abnormal(self, reason: str = "") -> None:
        """宿主加载失败等异常时调用，使心跳转为异常态向外广播。"""
        with self._state_lock:
            self._state = "abnormal"
            self._abnormal_reason = reason

    def _start_heartbeat(self) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                if not self._paused:
                    self._beat()
                self._stop.wait(self.heartbeat_interval)
        threading.Thread(target=loop, daemon=True).start()

    # ---- 加载数据包：首次主动推送 ----

    def _push_load_packet(self) -> None:
        packet = {
            "type": "load_packet",
            "uuid": self.uuid,
            "boot": {
                "name": self.name, "bus": self.bus, "isolation": self.isolation,
                "heartbeat_interval": self.heartbeat_interval, "version": self.version,
            },
            "control_codes": self.schema(),
            "content": self._host_content(),
        }
        with self._queue_lock:
            self._outbox.append(packet)

    def _host_content(self) -> Any:
        """宿主可经 host.chip_content() 提供加载包内容明细；缺省为空。"""
        if self.host is not None and hasattr(self.host, "chip_content"):
            try:
                return self.host.chip_content()
            except Exception:  # noqa: BLE001  宿主内容探测失败不影响加载包推送
                return None
        return None

    # ---- 传出 / 传入 总线 ----

    def drain(self) -> list[dict]:
        """传出：抽取并清空出站队列（心跳 + 加载包 + 出站数据）。"""
        with self._queue_lock:
            items = list(self._outbox)
            self._outbox.clear()
        return items

    def ingest(self, envelope: dict) -> dict:
        """传入：入站总线，按 type 路由。control→解码，data→数据通道，其余暂存。"""
        if not isinstance(envelope, dict):
            raise ValueError("envelope 须为 dict")
        etype = envelope.get("type")
        if etype == "control":
            try:
                return {"ok": True, "result": self.control(
                    envelope.get("code"), envelope.get("params"))}
            except Exception as exc:  # noqa: BLE001  转发层错误原样回传
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if etype == "data":
            return {"ok": True, "data": self.data(envelope.get("payload"))}
        with self._queue_lock:
            self._inbox.append(envelope)
        return {"ok": True, "stored": True}

    # ---- 数据通道 ----

    def data(self, payload: Any = None) -> Any:
        """数据面：双向字符串载荷通道（与控制面分离）。提供载荷即写入并随传出广播。"""
        if payload is not None:
            with self._queue_lock:
                self._data = payload
                self._outbox.append({"type": "data", "payload": payload})
        return self._data

    # ---- 模式 / 状态 ----

    def schema(self) -> dict:
        """返回全部控制码表（标准码 + 注册码），供主板/外部发现。"""
        table = {
            "0x%08X" % STD_STATUS: "芯片状态聚合",
            "0x%08X" % STD_SCHEMA: "返回本控制码表",
            "0x%08X" % STD_HEARTBEAT: "返回心跳信号",
            "0x%08X" % STD_SHUTDOWN: "关闭：停心跳线程并标记 shutdown（不可逆）",
            "0x%08X" % STD_RELEASE_PERF: "释放性能：暂停心跳广播、释放缓存，进入 idle 低占用态",
            "0x%08X" % STD_RESUME: "恢复：退出 idle 低占用态、重启心跳广播",
            "0x%08X" % STD_VERSION: "芯片版本",
            "0x%08X" % STD_RESET: "清空传出队列",
        }
        for code, (mode, fn) in self._registry.items():
            doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
            table["0x%08X" % code] = f"[{mode}] {doc or '未注明'}"
        return table

    def status(self) -> dict:
        with self._state_lock:
            state, reason = self._state, self._abnormal_reason
        return {
            "name": self.name, "bus": self.bus, "uuid": self.uuid, "state": state,
            "abnormal_reason": reason, "version": self.version,
            "registered_codes": len(self._registry),
            "heartbeat_interval": self.heartbeat_interval,
        }

    def shutdown(self) -> None:
        """关闭：停心跳线程并标记 shutdown；不可逆，需重建实例恢复。

        先触发宿主 on_shutdown 钩子（重型砖可借此 dispose/kill 子进程）。
        """
        self._call_host("on_shutdown")
        self._stop.set()
        with self._state_lock:
            self._state = "shutdown"
        self._beat()                  # 末次心跳广播关闭态

    def release_perf(self) -> None:
        """释放性能：暂停心跳广播、释放缓存载荷，进入 idle 低占用态。

        仅静默、不死亡——实例仍响应 control（可经 RESUME 恢复常态）。
        先触发宿主 on_release_perf 钩子（重型砖可借此暂停/降载子进程）。
        """
        self._call_host("on_release_perf")
        self._paused = True
        with self._state_lock:
            self._state = "idle"
        self._beat()                  # 末次心跳广播 idle 态（告知主板是主动静默）
        with self._queue_lock:
            self._data = None         # 释放缓存载荷占用的内存

    def resume(self) -> None:
        """恢复：退出 idle 低占用态，重启心跳广播。

        关闭（shutdown）不可逆——已停心跳线程且标记 shutdown，resume 不再复活，fail-closed。
        """
        with self._state_lock:
            if self._state == "shutdown":
                return
        self._paused = False
        with self._state_lock:
            self._state = "ready"
        self._beat()
