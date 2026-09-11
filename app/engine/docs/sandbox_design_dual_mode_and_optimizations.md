# 沙箱决策引擎双模式 + 性能优化 设计规格

> 范围：模块 E（决策引擎双模式）+ 优化 1~4。
> 输出形式：接口定义（Type Hints / ABC）+ 关键伪代码 + 代码量/依赖/内存估算 + 实施优先级。
> 目标：单模块新增常驻内存 ≤ 5MB，总新增 ≤ 10MB；优化项为负增长。

---

## 0. 范围说明与已知缺口

- **已覆盖**：模块 E、优化 1、优化 2、优化 3、优化 4。
- **已知缺口**：优先级中引用的「模块 A / B / C / D」**本需求未给出规格**，本节仅保留占位，待补充后并入。
- **文件定位校正**（按现有代码实测）：
  - `resolve_pid` 当前实现在 **`sandbox_net.py`**（非 spec 所称 `sandbox_run.py`）。
  - AST 静态分析在 **`sandbox_ast.py` 的 `analyze()`**（非 spec 所称 `sandbox_run.py.analyze_code`）。
  - 优化 3 的挂起点在 **`sandbox_net.py.NetInterceptor` + `web.py /api/net/pending`**。
- **显式否决（禁止实现）**：
  - ❌ 常驻后台蜜罐进程（优化 2 的异步线程仅在沙箱**子进程内**生命周期，非独立常驻）。
  - ❌ 运行时删除其他平台资产文件。
  - ❌ Docker / VM / 额外常驻守护进程。

---

## 模块 E：决策引擎双模式（小白 vs 正常）

### E.1 接口定义

```python
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

class DecisionMode(enum.Enum):
    BEGINNER = "beginner"   # 小白模式（默认）
    NORMAL = "normal"       # 正常模式

@dataclass
class DecisionContext:
    """一次待裁决请求的可观测数据。"""
    host: str
    port: int
    path: str
    pid: int | None
    is_private_ip: bool
    risk: str                       # low | medium | high（来自现有威胁/白名单判定）
    raw_technical: dict = field(default_factory=dict)   # 原始 IP/端口/Path 快照

@dataclass
class DecisionOutcome:
    action: str                    # "auto_allow" | "auto_deny" | "popup" | "log_only"
    popup_required: bool
    popup_text: str                # 小白模式留空；正常模式=原始技术数据
    delay_sec: int = 0             # 正常模式强制阅读延迟
    reason: str = ""

@runtime_checkable
class DecisionStrategy(Protocol):
    mode: DecisionMode
    def decide(self, ctx: DecisionContext) -> DecisionOutcome: ...

class BeginnerStrategy:
    """小白模式：零弹窗；后台规则引擎 + 可选 LLM API 裁决；前端仅滚动日志。"""
    mode = DecisionMode.BEGINNER
    def __init__(self, llm_endpoint: str | None = None) -> None: ...
    def decide(self, ctx: DecisionContext) -> DecisionOutcome: ...

class NormalStrategy:
    """正常模式：仅中风险弹窗，文案用原始技术数据，按钮延迟 10s 可点击。"""
    mode = DecisionMode.NORMAL
    POPUP_DELAY_SEC = 10
    def decide(self, ctx: DecisionContext) -> DecisionOutcome: ...

class ModeManager:
    """从环境变量 SANDBOX_MODE + 前端设置解析当前模式，提供策略实例。"""
    def __init__(self, env_mode: str | None = None,
                 setting_mode: str | None = None) -> None: ...
    @property
    def strategy(self) -> DecisionStrategy: ...
    @property
    def mode(self) -> DecisionMode: ...
```

### E.2 小白模式（默认）

- **零弹窗**：所有内网决策不进入「待用户裁决」挂起态，直接由 `BeginnerStrategy` 后台裁决。
- **pending_version 仍正常递增**：小白模式下网络拦截照常产生连接记录，`pending_version` **正常递增**（后端需感知新连接、供优化 3 增量轮询）；仅**前端 UI 层不渲染待审列表**，后台日志与审计照常记录。即「不弹窗 ≠ 不记录」。
- **裁决来源**：
  1. 现有规则引擎优先级（白名单 → 黑名单 → 威胁评级）；
  2. 可选 LLM API：对 `risk=medium` 的模糊请求，调用已保存的 `sandbox_net_adjudicator_prompt.md` 语义裁决（见同项目 prompt 文件），仅取 `action`/`confidence`/`reason`。
- **前端**：仅通过「统筹控制台」滚动日志展示活动（无交互式弹窗）；高风险默认 `auto_deny` 并记日志。

### E.3 正常模式

- **仅中风险弹窗**：`risk in ("medium",)` 且 `is_private_ip=True`（未知内网 IP）才弹窗；`low` 自动放行，`high` 自动拒绝（不弹窗）。
- **文案用原始技术数据**：`popup_text` 直接填 `ctx.raw_technical`（IP/端口/Path 原文），不做白话翻译。
- **按钮延迟 10 秒**：`delay_sec=10`，前端在该窗口内禁用确认按钮（强制阅读）。

### E.4 模式切换

- 优先级：`前端设置` > `环境变量 SANDBOX_MODE` > 默认 `beginner`。
- `ModeManager` 在 `web.py` 启动时实例化一次；`/api/run` 与 `_gate` 经其取 `strategy`。
- 前端「设置」面板新增「决策模式」开关，写回 `config.json`，下次请求生效（无需重启）。

### E.5 关键伪代码

```python
# BeginnerStrategy.decide
def decide(self, ctx):
    if ctx.risk == "high":
        return DecisionOutcome("auto_deny", popup_required=False,
                                reason="小白模式-高危自动拒绝")
    if ctx.risk == "low":
        return DecisionOutcome("auto_allow", popup_required=False,
                                reason="小白模式-低危自动放行")
    # medium：调用可选 LLM 裁决（失败则降级为 log_only + 默认放行）
    if self.llm_endpoint:
        r = call_llm_adjudicator(self.llm_endpoint, ctx)   # 复用 sandbox_net_adjudicator_prompt
        if r.action == "DENY":
            return DecisionOutcome("auto_deny", reason=r.reason)
        if r.action == "HUMAN_REQUIRED":
            return DecisionOutcome("log_only", reason=r.reason)   # 仍不弹窗，仅记录
    return DecisionOutcome("log_only", reason="小白模式-中危记录待查")

# NormalStrategy.decide
def decide(self, ctx):
    if ctx.risk == "high":
        return DecisionOutcome("auto_deny", popup_required=False, reason="高危自动拒绝")
    if ctx.risk == "low":
        return DecisionOutcome("auto_allow", popup_required=False, reason="低危自动放行")
    # medium → 弹窗，原始技术数据，10s 延迟
    return DecisionOutcome("popup", popup_required=True,
                           popup_text=json.dumps(ctx.raw_technical, ensure_ascii=False),
                           delay_sec=self.POPUP_DELAY_SEC, reason="中危未知内网待确认")
```

### E.6 估算

| 项 | 值 |
|----|----|
| 代码量 | ~180 行（接口 + 2 策略 + ModeManager + 前端开关） |
| 依赖 | 仅标准库（`enum`/`dataclasses`/`typing`/`json`）；LLM 调用走现有 HTTP 客户端 |
| 内存增量 | ≈ 0.3 MB（枚举/字典/策略实例，进程内常驻） |
| 跨平台 | 纯逻辑，无平台分支 |

---

## 优化 1：剔除 `psutil`，轻量 PID 反查 + 1 秒缓存

> 当前实现：`sandbox_net.py:282 resolve_pid`（psutil + netstat 回退）。改造为**纯标准库**（ctypes / 解析 /proc / sysctl）。

### 1.1 接口定义

```python
from __future__ import annotations
import ctypes
import threading
from typing import Dict, Optional

class PIDResolver:
    """跨平台 PID 反查；原生 API 失败返回 None，不阻塞业务。"""
    def __init__(self, cache_ttl: float = 1.0) -> None:
        self._cache_ttl = cache_ttl
        self._cache: Dict[int, "tuple[float, Optional[int]]"] = {}
        self._lock = threading.Lock()

    def resolve(self, local_port: int) -> Optional[int]:
        now = time.monotonic()
        with self._lock:
            ts, pid = self._cache.get(local_port, (0.0, None))
            if now - ts < self._cache_ttl:
                return pid                      # 命中缓存：跳过真实查询
        pid = self._resolve_native(local_port)  # 平台分支
        with self._lock:
            self._cache[local_port] = (now, pid)
        return pid

    def _resolve_native(self, port: int) -> Optional[int]:
        if sys.platform == "win32":   return self._win32(port)
        if sys.platform == "linux":   return self._linux(port)
        if sys.platform == "darwin":  return self._macos(port)
        return None
```

### 1.2 平台分支伪代码

```python
# Windows：ctypes 调 iphlpapi.GetExtendedTcpTable（无 psutil）
def _win32(self, port):
    try:
        iphlpapi = ctypes.windll.iphlpapi
        # 先取所需缓冲区大小，再分配，再解析 MIB_TCPTABLE_OWNER_PID
        # 遍历每行：state==ESTABLISHED 且 dwLocalPort(网络序) 解码==port → 返回 dwOwningPid
    except OSError:
        return None   # 降级，不抛

# Linux：解析 /proc/net/tcp + /proc/[pid]/fd 反查 inode
def _linux(self, port):
    try:
        # 1) 读 /proc/net/tcp，找 local_address 端口==port 且 st==0x01(ESTABLISHED) 的 inode
        # 2) 遍历 /proc/[0-9]*/fd/*，readlink 命中该 inode → 返回 pid（int(path)）
    except (PermissionError, FileNotFoundError, OSError):
        return None

# macOS：sysctl 为主；仅当所有原生方法失败后才回退 lsof（限频）
_LSOF_MAX_PER_MIN = 3          # 全局每分钟最多 3 次（lsof 开销大，频繁调用显著拖慢系统）
_lsof_window_start: float = 0.0
_lsof_calls: int = 0

def _macos(self, port):
    try:
        return self._sysctl_tcp(port)   # sysctl net.inet.tcp.pcblist，匹配本地端口+ESTABLISHED
    except Exception:
        return self._lsof(port)         # 所有原生方法失败才回退 lsof

def _lsof(self, port):
    # 全局限频：每分钟最多 _LSOF_MAX_PER_MIN 次；超限或失败直接返回 None，不重试、不阻塞业务
    now = time.monotonic()
    with self._lock:
        if now - self.__class__._lsof_window_start >= 60.0:
            self.__class__._lsof_window_start = now
            self.__class__._lsof_calls = 0
        if self.__class__._lsof_calls >= self.__class__._LSOF_MAX_PER_MIN:
            return None
        self.__class__._lsof_calls += 1
    try:
        out = subprocess.run(["lsof", "-i", f":{port}"],
                              capture_output=True, text=True, timeout=5,
                              check=False).stdout or ""
        # 解析输出首列取 PID（ESTABLISHED 行）
    except Exception:
        return None            # lsof 也失败 → 直接 None，不再重试
    return None
```

> **macOS 回退限频说明**：`lsof -i :port` 仅在 `sysctl` 原生方法**全部失败**后才调用；全局每分钟**最多 3 次**（`_LSOF_MAX_PER_MIN=3`），超限直接返回 `None`；若 `lsof` 本身也失败，直接返回 `None`，**不重试**，绝不阻塞业务。

### 1.3 估算

| 项 | 值 |
|----|----|
| 代码量 | ~150 行（3 平台分支 + 缓存） |
| 依赖 | 仅 `ctypes`/`threading`/`os`/`sys`（标准库）；**移除 psutil** |
| 内存增量 | ≈ 0.05 MB（缓存字典，TTL 自动过期）；净效应为正向（去掉 psutil 懒加载常驻） |
| 跨平台 | win32 / linux / darwin 三分支，均标准库实现 |

---

## 优化 2：蜜罐日志异步批处理

> 当前实现：`sitecustomize.py:_log` 每次事件**同步** `open(...,"a")` 追加。改为队列 + 后台线程批量写。

### 2.1 接口定义

```python
from __future__ import annotations
import atexit
import threading
from collections import deque
from typing import Deque, Dict, List

class AsyncLogWriter:
    FLUSH_INTERVAL = 2.0      # 秒
    FLUSH_BATCH = 50          # 队列满即刷
    def __init__(self, path: str) -> None:
        self._path = path
        self._queue: Deque[Dict] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        atexit.register(self.flush)     # 进程退出前强制刷新

    def emit(self, rec: Dict) -> None:
        with self._lock:
            self._queue.append(rec)
            if len(self._queue) >= self.FLUSH_BATCH:
                self._cv.notify_all()

    def _run(self) -> None:
        while not self._stop:
            with self._cv:
                self._cv.wait(timeout=self.FLUSH_INTERVAL)
                batch = list(self._queue)
                self._queue.clear()
            if batch:
                self._write(batch)       # 单文件追加多行，包 PermissionError/FileNotFoundError

    def flush(self) -> None:
        with self._lock:
            batch = list(self._queue); self._queue.clear()
        if batch: self._write(batch)
        self._stop = True
```

### 2.2 伪代码（shim 改造）

```python
# sitecustomize.py 模块级
_writer = AsyncLogWriter(EVENT_LOG) if EVENT_LOG else None

def _log(path, sig_id, action, strategy):
    if _writer is None: return
    _writer.emit({"ts": time.time(), "pid": os.getpid(), "path": str(path),
                  "sig": sig_id, "action": action, "strategy": strategy})
```
- `honeypot_node.js` 等价：模块级 `const writer = new AsyncLogWriter(...)`，`emit()` 推入 JS 数组 + `setInterval(2000)` / 满 50 条写盘。**注意**：Node 的 `process.on('exit')` 是**同步事件，无法执行异步 `fs.write`**，不能作为刷新点。改用：
  - `process.on('beforeExit', () => setTimeout(() => writer.flush(), 100))`：`beforeExit` 时事件循环仍存活，用 `setTimeout(100ms)` 强制延迟确保队列落盘；
  - 或主进程退出时经 IPC 向 Node 子进程发送 `SIGUSR1`，子进程监听 `process.on('SIGUSR1', () => writer.flush())` 触发刷新。
  - `flush()` 内部使用**同步 `fs.writeFileSync`/`fs.appendFileSync`**（退出路径不可用异步 API）。

### 2.3 估算

| 项 | 值 |
|----|----|
| 代码量 | ~100 行（Python shim ~70 + Node ~30） |
| 依赖 | 仅标准库（`collections.deque`/`threading`/`atexit`）；JS 用 `setInterval`/`process` |
| 内存增量 | ≈ 0.2 MB（队列缓冲 + 线程栈）；I/O 次数从 N→N/50，降低文件锁竞争 |
| 跨平台 | 纯标准库，无平台分支；`daemon=True` 不阻碍解释器退出 |

---

## 优化 3：前端轮询增量版本号

> 当前实现：`web.py /api/net/pending` 每次 `itc.list_pending()`（含 `resolve_pid` 反查）。加版本号：`since` 未变则跳过反查。
> **与模块 E 集成**：小白模式下 `pending_version` 仍正常递增（见 §E.2），仅前端 UI 不渲染待审列表，后端日志照常记录；本优化对两种模式均生效。

### 3.1 接口定义

```python
# sandbox_net.py NetInterceptor 新增
class NetInterceptor:
    def __init__(self, *a, **k):
        self.pending_version: int = 0
        ...
    def _bump_pending_version(self) -> None:
        with self.pending_lock:
            self.pending_version += 1     # 每次新增/移除 pending 时调用

    def list_pending_since(self, since: int | None) -> Dict:
        with self.pending_lock:
            if since is not None and since == self.pending_version:
                return {"changed": False}          # 跳过 PID 反查
            return {"changed": True,
                    "version": self.pending_version,
                    "pending": [p.to_dict() for p in self.pending.values()]}
```

### 3.2 伪代码（web.py GET）

```python
if path == "/api/net/pending":
    itc = sandbox_net.get_interceptor()
    if not itc:
        return self._send_json({"enabled": False, "pending": []})
    q = urllib.parse.parse_qs(parsed.query)
    since_s = (q.get("since") or [None])[0]
    since = int(since_s) if since_s and since_s.isdigit() else None
    return self._send_json(itc.list_pending_since(since))   # 未变 → {"changed": false}
```
- 前端：记录上次 `version`，轮询带 `?since=version`；收到 `changed:false` 直接跳过渲染与任何反查结果解析。

### 3.3 估算

| 项 | 值 |
|----|----|
| 代码量 | ~50 行（拦截器版本维护 + web 端点 + 前端轮询改造） |
| 依赖 | 无新增（复用现有 `PendingRequest.to_dict`） |
| 内存增量 | ≈ 0.05 MB（单个 int 版本号） |
| 跨平台 | 无平台分支 |
| 收益 | 未变更时节省 `resolve_pid` 反查（优化 1 的缓存之上再省一次调用栈） |

---

## 优化 4：AST 大代码截断

> 当前实现：`sandbox_ast.py analyze()` 直接 `ast.parse(code)`，无上限。加 200KB / 5000 行截断。

### 4.1 接口定义

```python
# sandbox_ast.py
MAX_AST_BYTES = 200 * 1024
MAX_AST_LINES = 5000

def _truncate_for_ast(code: str) -> "tuple[str, bool]":
    """返回 (截断后代码, 是否触发截断)。超出部分忽略并记录警告。"""
    if len(code) > MAX_AST_BYTES:
        return code[:MAX_AST_BYTES], True
    lines = code.split("\n")
    if len(lines) > MAX_AST_LINES:
        return "\n".join(lines[:MAX_AST_LINES]), True
    return code, False
```

### 4.2 伪代码

```python
# CodeAnalyzer.analyze_python 开头
def analyze_python(self, code):
    code, truncated = _truncate_for_ast(code)
    if truncated:
        _warn("AST 分析已截断至 %dKB/%d 行，超出部分忽略" % (...))
    try:
        tree = ast.parse(code)      # 仅扫描截断后的子集
    ...
# analyze_js 同样在正则扫描前截断
```
- 截断**不影响真实执行**（执行走 `sandbox_run.py`，不经此分析）；仅降低预分析开销与内存峰值。
- **风险说明（覆盖率）**：截断可能导致 AST 预分析**覆盖率下降**（超大代码尾部不被扫描），但**网络代理层仍作为兜底防线**（`_gate` 对所有出站连接做裁决），截断不影响最终安全；该取舍为有意为之，未来被质疑时可据此回溯。

### 4.3 估算

| 项 | 值 |
|----|----|
| 代码量 | ~25 行（截断函数 + 两处调用 + 警告日志） |
| 依赖 | 无新增 |
| 内存增量 | ≈ 0 MB 新增；**净负增长**（避免对超大代码做完整 AST 解析的内存峰值） |
| 跨平台 | 无平台分支 |

---

## 汇总表

| 模块 | 代码量 | 新增依赖 | 内存增量 | 优先级 |
|------|--------|----------|----------|--------|
| 模块 E 双模式 | ~180 行 | 无 | ≈ 0.3 MB | P2 |
| 优化 1 PID 反查 | ~150 行 | **移除 psutil** | ≈ +0.05 MB（净省 psutil 常驻） | **P0** |
| 优化 2 日志异步 | ~100 行 | 无 | ≈ +0.2 MB | **P0** |
| 优化 3 增量版本 | ~50 行 | 无 | ≈ +0.05 MB | **P0** |
| 优化 4 AST 截断 | ~25 行 | 无 | ≈ 0 MB（净负） | （随 AST 模块） |
| **合计新增常驻** | ~505 行 | — | **≈ 0.6 MB（远 ≤ 10 MB）** | — |

> 注：模块 A/B/C/D 待规格补充后并入，届时更新本表。

## 实施优先级建议

- **P0（必须立即做）**：优化 1、优化 2、优化 3 —— 直接降延迟/降 I/O/降反查开销，且无行为风险。
- **P1（功能补充）**：模块 A、模块 D（规格待补）。
- **P2（扩展兼容）**：模块 B、模块 C、模块 E（双模式）—— 属体验与策略增强，可后置。

## 约束合规清单

- ✅ 单模块新增常驻内存 ≤ 5MB；合计 ≈ 0.6 MB（优化项为负/零增长）。
- ✅ 禁止引入 `psutil` / `watchdog` / `PyObjC` 等重型第三方库（优化 1 移除 psutil）。
- ✅ 所有文件操作包 `PermissionError` / `FileNotFoundError`，失败降级（优化 2 `_write`、优化 1 各平台分支）。
- ✅ 兼容 Windows（非管理员）/ macOS / Linux 主流发行版（优化 1 三平台分支；其余纯标准库）。
- ✅ 无 Docker / VM / 常驻守护进程；优化 2 的异步线程仅在沙箱子进程生命周期内，非独立常驻。
- ✅ 类型：全部模块提供 Type Hints，可过 `mypy --strict`（建议为 `ctypes` 结构补 `# type: ignore` 或 stub）。
