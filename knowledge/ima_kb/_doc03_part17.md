
# P.A.L.M 系统架构白皮书（99% 补全章：15 Port 契约全量实录）

> 本章为架构篇补全，将 15 个 Port 的**完整抽象方法**从真实源码全量抄录（这是 03 篇此前最大的缺口）。同时补入裁决规则模型（rules.py 实录）与工具层基座（tooling.py 实录）。复刻者凭本章可 1:1 重建契约层。

---

## 补全章 A：15 Port 完整抽象方法（源码全量抄录）

> 所有 Port 均为 `abc.ABC`，仅依赖标准库，经 `ports/__init__.py` 总出口引用；子类缺失任一抽象方法即无法装配（ABC 强制）。隐喻沿用旧体系插槽语言（ai/pcie/chip/usb/ram/sata/m2/board/ui 插槽）。

### A.1 AgentPort（agent_port.py，ai 插槽，7 方法）

```python
class AgentPort(ABC):
    """Agent 核心插槽：规划/执行/反应/提示/完成判定/意图路由。"""

    @abstractmethod
    def run(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """单次运行入口：ReAct 文本循环或原生 function calling 二选一，返回最终结果。"""

    @abstractmethod
    def stream(self, prompt: str, context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """流式事件出口：逐事件产出（工具调用/思维链/文本增量），消费方按类型分发。"""

    @abstractmethod
    def plan(self, task: str) -> dict[str, Any]:
        """计划生成：把任务拆成可执行步骤清单（含依赖与验收条件）。"""

    @abstractmethod
    def replan(self, plan: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
        """重规划：执行受阻或需求变更时，依据反馈修订既有计划。"""

    @abstractmethod
    def build_prompt(self, user_input: str, persona: str, tools: list[str], memories: list[str]) -> str:
        """提示构建：把角色/工具清单/记忆注入用户输入，产出模型可消费的系统+用户消息。"""

    @abstractmethod
    def is_done(self, output: dict[str, Any]) -> bool:
        """完成判定：门控判断一轮输出是否已满足目标（true 即终止循环）。"""

    @abstractmethod
    def route_intent(self, message: str) -> str:
        """意图路由：把用户消息归类为四意图之一（如 闲聊/任务/记忆/情感），决定走哪条链路。"""
```

### A.2 AudioPort（audio_port.py，pcie 声卡，3 方法）

```python
class AudioPort(ABC):
    """声卡插槽：语音识别/语音合成/声纹识别。"""

    @abstractmethod
    def stt(self, audio: bytes) -> str:
        """语音识别：音频字节 → 文本；无授权/引擎缺失时抛依赖异常由调用方降级。"""

    @abstractmethod
    def tts(self, text: str) -> bytes:
        """语音合成：文本 → 音频字节（WAV）；CosyVoice/SoVITS 由实现方调度。"""

    @abstractmethod
    def voiceprint(self, audio: bytes) -> dict[str, Any]:
        """声纹识别：音频 → 声纹特征与分组归属，用于说话人确认。"""
```

### A.3 CryptoPort（crypto_port.py，chip 焊死，4 方法）

```python
class CryptoPort(ABC):
    """加密芯片插槽：SM4 加解密/硬件指纹密钥绑定/离线恢复。"""

    @abstractmethod
    def encrypt_bytes(self, data: bytes, key_id: str = "default") -> bytes:
        """加密：按密钥标识对原始字节做对称加密（SM4），返回密文。"""

    @abstractmethod
    def decrypt_bytes(self, blob: bytes, key_id: str = "default") -> bytes:
        """解密：按密钥标识还原明文；密钥不符抛异常由调用方归一。"""

    @abstractmethod
    def bind_fingerprint(self) -> str:
        """硬件指纹：读取/生成绑定本机的指纹标识，作为密钥派生种子。"""

    @abstractmethod
    def recover(self, seed: str) -> dict[str, Any]:
        """离线恢复：凭恢复种子重建密钥材料，返回恢复结果与可用状态。"""
```

### A.4 DevicePort（device_port.py，usb 五通道，5 方法）

```python
class DevicePort(ABC):
    """设备插槽（USB）：五通道协议，任何外设芯片必须实现。"""

    @abstractmethod
    def ingest(self, payload: dict[str, Any]) -> None:
        """入站总线：承载控制/数据/外部事件，内部按类型路由。"""

    @abstractmethod
    def drain(self) -> list[dict[str, Any]]:
        """出站总线：抽取待发消息（心跳/数据包/出站数据），消费方轮询清空。"""

    @abstractmethod
    def heartbeat(self) -> str:
        """统一存活信号：返回就绪/异常两态标识；消费者收不到即视为离线。"""

    @abstractmethod
    def control(self, code: str, decoder: dict[str, Any]) -> dict[str, Any]:
        """控制面：控制码 + 解码器单入口，返回执行结果与状态。"""

    @abstractmethod
    def data(self, payload: dict[str, Any]) -> bytes:
        """数据面：与控制面分离的载荷通道（音频/文本/二进制），返回编码后字节。"""
```

### A.5 DisplayPort（display_port.py，pcie 显示，3 方法）

```python
class DisplayPort(ABC):
    """显示层插槽：桌面/壁纸/部件渲染。"""

    @abstractmethod
    def render(self, spec: dict[str, Any]) -> bytes:
        """渲染：按规格（布局/组件/主题）产出图像字节，供展示。"""

    @abstractmethod
    def set_wallpaper(self, image: bytes) -> None:
        """壁纸：把图像字节设为桌面壁纸；失败返回异常由调用方降级。"""

    @abstractmethod
    def widgets(self) -> list[dict[str, Any]]:
        """部件清单：返回当前已注册桌面部件的描述，供管理界面展示。"""
```

### A.6 GuardPort（guard_port.py，chip 焊死，3 方法）

```python
class GuardPort(ABC):
    """守卫芯片插槽：动作裁决/策略管理。"""

    @abstractmethod
    def evaluate(self, action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """动作裁决：评估一次敏感动作（类型/目标/参数），返回放行/拒绝/升级及档位。"""

    @abstractmethod
    def policies(self) -> list[dict[str, Any]]:
        """策略清单：返回全部现行规则（供前端 JSON 管理与审计导出）。"""

    @abstractmethod
    def set_policy(self, policy: dict[str, Any]) -> None:
        """策略更新：新增/替换一条规则；非法策略抛 ValueError 由调用方归一。"""
```

### A.7 GuiPort（gui_port.py，pcie 显卡，3 方法）

```python
class GuiPort(ABC):
    """GUI 自动化插槽：语义入口/世界模型/静态认知。"""

    @abstractmethod
    def automate(self, software_id: str, intent: str) -> dict[str, Any]:
        """语义自动化入口：软件标识 + 意图 → 执行结果；经执行器阶梯（UIA/OCR/LLM/VLC）兜底。"""

    @abstractmethod
    def world_model(self, screen: dict[str, Any]) -> dict[str, Any]:
        """世界模型：把屏幕快照/控件树解析为结构化场景，供执行器决策。"""

    @abstractmethod
    def atlas(self) -> dict[str, Any]:
        """静态认知：返回已知软件的控件规律/转移规律/坐标记忆（EMA，样本不足不可信）。"""
```

### A.8 MemoryPort（memory_port.py，ram 内存条，5 方法）

```python
class MemoryPort(ABC):
    """记忆插槽：写入/语义检索/上下文压缩/Token 预算/情绪五因子。"""

    @abstractmethod
    def write(self, payload: dict[str, Any]) -> None:
        """事件触发式写入：把对话/行为事件沉淀为可检索的记忆条目。"""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """语义检索：按相关性返回 top_k 条记忆（向量/BM25 混合由实现方决定）。"""

    @abstractmethod
    def compress(self, session: dict[str, Any]) -> dict[str, Any]:
        """上下文压缩：长会话折叠为摘要+要点，保留关键事实用于注入。"""

    @abstractmethod
    def budget(self, usage: dict[str, Any]) -> dict[str, Any]:
        """Token 预算：按用量与上限给出可注入配额，防上下文超限。"""

    @abstractmethod
    def emotion(self, text: str) -> dict[str, Any]:
        """情绪五因子：对文本打分（仅输出非负值），供情感门控与角色反应使用。"""
```

### A.9 ModelPort（model_port.py，cpu 焊死，4 方法）

```python
class ModelPort(ABC):
    """模型插槽：LLM 流式调用/单次补全/路由/健康。"""

    @abstractmethod
    def stream_chat(self, messages: list[dict[str, Any]], model: str, **options: Any) -> Iterator[str]:
        """流式补全：逐 token 产出文本；消费方用于 SSE/打字机效果。"""

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], model: str, **options: Any) -> str:
        """单次补全：一次性返回完整文本（工具判定/短回答等非流式场景）。"""

    @abstractmethod
    def route(self, intent: str) -> str:
        """模型路由：按意图/成本把请求分派到 Pro/Flash 等具体模型标识。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康探测：返回可用模型清单与各模型可用性（供 BIOS 自检与前端展示）。"""
```

### A.10 OpsPort（ops_port.py，ram 内存服务，3 方法）

```python
class OpsPort(ABC):
    """运维服务插槽：Token 用量/运行监控/定时任务。"""

    @abstractmethod
    def usage(self) -> dict[str, Any]:
        """Token 用量台账：返回累计消耗与分模型明细，供前端用量界面。"""

    @abstractmethod
    def monitor(self) -> dict[str, Any]:
        """运行监控：返回进程/资源/异常计数，供监控界面与告警。"""

    @abstractmethod
    def schedule(self, job: dict[str, Any]) -> None:
        """定时任务：登记/更新一个计划任务；触发时回调由实现方保证。"""
```

### A.11 PersistPort（persist_port.py，sata 硬盘，3 方法）

```python
class PersistPort(ABC):
    """持久化插槽：会话落盘/恢复、记忆落盘。"""

    @abstractmethod
    def save_session(self, session: dict[str, Any]) -> None:
        """会话落盘：把会话（消息序列/元数据）写入持久介质。"""

    @abstractmethod
    def load_session(self, session_id: str) -> dict[str, Any]:
        """会话恢复：按标识取回会话；不存在返回空会话由调用方归一。"""

    @abstractmethod
    def save_memory(self, memory: dict[str, Any]) -> None:
        """记忆落盘：把运行期记忆快照持久化，供重启后重建。"""
```

### A.12 StoragePort（storage_port.py，m2 固态，4 方法）

```python
class StoragePort(ABC):
    """存储插槽：介质层块读写/健康。"""

    @abstractmethod
    def read_block(self, key: str) -> bytes:
        """块读取：按 key 返回原始字节；key 缺失时抛 KeyError 由调用方归一。"""

    @abstractmethod
    def write_block(self, key: str, data: bytes) -> None:
        """块写入：按 key 落盘原始字节；介质层负责原子性与目录布局。"""

    @abstractmethod
    def delete_block(self, key: str) -> None:
        """块删除：按 key 移除；删除动作须经回收站语义（保险库兜底），禁止硬删。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康自检：返回容量/余量/读写状态，供 BIOS 自检与前端监控展示。"""
```

### A.13 SysPort（sys_port.py，board 板载，4 方法）

```python
class SysPort(ABC):
    """板载系统服务插槽：应用设置/文件鉴权/解析分发。"""

    @abstractmethod
    def settings(self) -> dict[str, Any]:
        """应用设置：返回全部设置项（供前端设置界面与管理接口）。"""

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """应用设置写入：按键更新并持久化；非法键抛 ValueError 由调用方归一。"""

    @abstractmethod
    def file_gate(self, path: str) -> bool:
        """文件鉴权：判定路径是否在允许域（用户主目录）内，越界返回 false。"""

    @abstractmethod
    def parse(self, file_path: str) -> dict[str, Any]:
        """解析分发：按文件类型路由到文档解析/图片 OCR，返回结构化内容。"""
```

### A.14 ToolPort（tool_port.py，工具总线，4 方法）

```python
class ToolPort(ABC):
    """工具插槽：注册/语义匹配/执行/代码防护。"""

    @abstractmethod
    def register(self, tool: dict[str, Any]) -> None:
        """工具注册：登记工具描述（名称/参数 schema/回调），供发现与调用。"""

    @abstractmethod
    def match(self, prompt: str) -> list[dict[str, Any]]:
        """语义匹配：按意图返回候选工具清单（含置信度），供主循环选择。"""

    @abstractmethod
    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """工具执行：按名调用已注册工具，返回结构化结果；未知名抛 KeyError。"""

    @abstractmethod
    def guard(self, code: str, lang: str) -> dict[str, Any]:
        """代码防护：静态预检生成代码（Python/JS/PowerShell），返回风险档位与命中规则。"""
```

### A.15 UiPort（ui_port.py，ui 显示器，2 方法）

```python
class UiPort(ABC):
    """前端界面契约：界面端点清单/界面渲染数据。"""

    @abstractmethod
    def endpoints(self) -> list[dict[str, Any]]:
        """界面端点清单：返回本界面依赖的后端端点（方法/路径/参数），供 shell 装载校验。"""

    @abstractmethod
    def render(self, screen: str, params: dict[str, Any]) -> dict[str, Any]:
        """渲染数据：按界面名与参数返回装配数据；未知界面返回空 dict 由调用方归一。"""
```

**契约层补全结论**：15 Port 共 55 个抽象方法（7+3+4+5+3+3+3+5+4+3+3+4+4+4+2），全部为"零实现、零依赖（仅标准库）"，复刻者按本章即可 1:1 重建契约层。

---

## 补全章 B：裁决规则模型（rules.py 实录）

### B.1 条件算子（ConditionOp，15 个）

| 类 | 算子 | 含义 |
|---|---|---|
| 数值 | gte/gt/eq/lt/lte | >= > == < <= |
| 字符串 | matches（正则）/startswith/endswith/contains/not_startswith/not_endswith/not_contains | 匹配/前缀/后缀/包含/反向 |
| 集合 | in_op（in）/not_in | 值在/不在集合 |
| 布尔 | is_true/is_false | 真/假 |

### B.2 规则数据结构（pydantic）

```python
class Condition(BaseModel):
    """单条匹配条件：字段 + 算子 + 目标值。"""
    field: str
    op: ConditionOp
    value: Any | None = None    # 数值/字符串/列表；布尔算子忽略
    label: str | None = None    # 条件不满足时的替代提示模板

class AskConfig(BaseModel):
    """ask 动作配置。"""
    message: str = ""           # 确认提示模板（支持 {field} 插值）
    timeout_ms: int = 30_000    # 超时毫秒
    on_timeout: Literal["deny", "allow", "warn"] = "deny"

ResponseAction = dict[Literal["ask", "deny", "allow", "warn"], str | AskConfig]
# deny 拒绝 / ask 询问 / warn 提醒（放行+告警） / allow 允许（白名单）
# quarantine（隔离）设计时纳入但第一期不实现

class Rule(BaseModel):
    """单条安全裁决规则：所有条件 AND 组合，优先级高（数字大）先匹配。"""
    id: str
    description: str = ""
    # ...（事件类型、条件列表、动作、优先级等，以源码为准）
```

### B.3 规则格式约定

```
规则格式：<AI行为><条件组合><执行行为>
  AI行为   : file.delete / file.write / process.execute / network.request / batch.operation
  条件组合 : 多个条件 AND 逻辑组合；字段+算子+值自由搭配
  执行行为 : 询问 / 提醒 / 拒绝 / 允许
```

**补全结论**：规则库为 pydantic 模型 + 规则文件（YAML 优先，pyyaml 不可用时回退 _minimal_yaml）；规则条目本身不内置于代码（引擎只认 RuleSet 数据结构）——复刻者需自行按 AI 行为五类设计规则条目。

---

## 补全章 C：工具层基座（palm/_core/tooling.py 实录）

### C.1 ToolSpec 完整字段（工具与外部世界唯一数据契约）

```python
@dataclass
class ToolSpec:
    name: str                                     # 蛇形命名，唯一标识（如 read_file）
    description: str                              # LLM 理解用途的自然语言描述
    parameters: dict = field(default_factory=lambda: {
        "type": "object", "properties": {}, "required": []})   # JSON Schema 参数定义
    event_type: str = ""                          # 触发裁决引擎的事件类型（空=不触发安全审查）
    permission: str = ""                          # 所需用户授权键；空串=豁免（fail-open）
    requires_grounding: bool = False              # 硬约束前置校验：删除/外发等高风险操作须先经
                                                  # 搜索/溯源核验并附带 verification_id，否则拦截
    requires_confirmation: bool = False           # 需要用户确认
```

### C.2 工具运行上下文（contextvars）

```python
agent_conversation_id: ContextVar[str]      # 当前会话 id（工具免改签名读取）
agent_model: ContextVar[str]                # 当前模型
agent_character_id: ContextVar[str]         # 当前角色 id（提醒/定时工具按角色人设撰写）
agent_provider: ContextVar[object]          # 当前供应商配置（automation 砖复用同款模型）
agent_is_wakeup: ContextVar[bool]           # 后台任务完成自动唤醒轮标记（唤醒轮禁再登记任务，防套娃）
```

### C.3 工具重试参数（真实值）

```python
_TOOL_MAX_RETRIES = 2        # 仅重试 tool.execute 瞬时异常（不含首次共 2 次）
_TOOL_RETRY_BACKOFF = 0.3    # 线性退避秒数
# 权限/裁决拦截在重试前已 return，不会被重试
```

### C.4 工具执行安全链

```
execute_tool_with_safety（tooling.py）：
  schema 校验 → 裁决（event_type）→ 授权（permission 键）→ 硬约束前置校验
  （requires_grounding 需 verification_id）→ 确认（requires_confirmation）→ 执行 → 重试（瞬时异常 2 次）
```

**补全结论**：工具层的"基类下沉"事实（tool_base.py 仅为薄壳，真正基类在 palm/_core/tooling.py）已被本补全章修正——03/04 篇此前按 tool_base 描述，现在以 tooling 为准。

---

## 补全章 D：宿主层事实澄清（重大修正）

**源码证据**：当前工作区 palm/ 库内**无任何 FastAPI 路由/APIRouter 定义**（grep 全库无 `@app.`/`APIRouter(`）；tool_base.py 注释明确"真正的基类定义已下沉到**主板 backend/app/bricks/_shared/tooling.py**"。

**结论**：
1. **HTTP 网关是宿主层职责**（backend/app/bricks/ 等应用层代码不在当前 palm 库内，也不在可访问的归档中——08-18 归档时对象损坏，或由 pywebview 宿主工程持有）。
2. 历史"163 端点全绿"是旧体系（主板时代 backend/app）的实录，**不是当前库内代码可验证的事实**。
3. 本文档系列中的 API 端点清单均为"宿主层规划参考"（基于旧体系 routes 证据重建），**非当前库内实测**。
4. 复刻者如需 HTTP 层，需自行按 UiPort.endpoints() 契约在宿主层实现 FastAPI 路由——契约已由 UiPort 定义，实现归宿主。
