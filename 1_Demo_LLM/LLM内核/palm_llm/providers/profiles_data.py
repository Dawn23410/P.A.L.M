"""Profile / ModelRule 规则数据（两级匹配的唯一事实来源）。

数据依据（均为厂商官方文档，2026-09-23 抓取/复审）：
  - `docs/各模型思考强度调研_v1.0.md`        —— 思考档位与模型级差异
  - `docs/同功能异字段差异矩阵_v1.0.md`      —— 同功能异字段
  - `docs/各供应商各模型支持能力_v2.0.md`    —— 多模态 / 文档 / 上限（能力矩阵的数据源）
  - `docs/思考块回传契约_v1.0.md`            —— 推理块回传（DeepSeek / Kimi 官方口径）

维护约定
--------
- 新增供应商：加一个 `Profile` + 一条 `DOMAIN_HINTS`。
- 新增模型：往对应 Profile 的 `model_rules` 里加一条 `ModelRule`，**不要加类**。
- 每条规则必须写 `as_of`；超过 90 天未复审的规则应重查官方文档。
- **模型下线/改名一律"保留 + 补 note"，不删规则**：删掉会让仍在用旧名的调用方
  直接匹配失败（回落 Profile 默认），而"它下线了"这件事应该留在数据里。
- 能力字段（supports_vision / doc_mimes / max_file_mb / reject_documents）会被
  `capability.py` 当作**硬闸门**使用：只有官方文档写明的才填，**未查到的留空**
  （空 = 不拦），不凭印象补。
"""
from __future__ import annotations

from .profiles import ModelRule, Profile

AS_OF = "2026-09-23"

GLM = Profile(
    name="glm",
    thinking_param="thinking_type",
    max_output=131072,
    supports_vision=True,
    doc_mimes=("application/pdf", "application/msword", "text/plain"),
    # ⚠️ 未查到 5.3-Flash 的文件体积上限，沿用 50 作保守闸门（勿当作官方值）
    max_file_mb=50,
    model_rules=(
        ModelRule(
            # 必须排在 glm-5.3 之前：只有 flash 支持文/图/视频/文件，5.3 是纯文本
            pattern=r"glm-5\.3-flash",
            priority=105, as_of=AS_OF,
            thinking="always_on",
            thinking_param="reasoning_effort",
            effort_allowed=("low", "high", "max"),
            fixed_params={"thinking": {"type": "enabled"}},
            forbid_params=("enable_thinking",),
            max_output=131072,
            supports_vision=True,
            note="GLM-5.3-Flash：唯一支持多模态+文件的 5.3 变体；思考强制开启，关闭报错",
        ),
        ModelRule(
            pattern=r"glm-5\.3",
            priority=100, as_of=AS_OF,
            thinking="always_on",
            thinking_param="reasoning_effort",
            effort_allowed=("low", "high", "max"),
            # 官方：5.3 强制开启，关闭报错；迁移时必须写成 enabled + low
            fixed_params={"thinking": {"type": "enabled"}},
            forbid_params=("enable_thinking",),
            max_output=131072,
            # 能力矩阵 v2.0：glm-5.3 输入模态只有"文本"
            supports_vision=False,
            reject_documents=True,
            note="GLM-5.3（文本）：仅支持 low/high/max，默认 max，关闭报错；不吃图也不吃文档",
        ),
        ModelRule(
            pattern=r"glm-5\.2(-flash)?",
            priority=90, as_of=AS_OF,
            thinking_param="reasoning_effort",
            effort_allowed=("none", "low", "high", "max"),
            # 官方：none/minimal 放弃思考；low/medium 映射为 high；xhigh 映射为 max
            effort_map={"minimal": "none", "low": "high", "medium": "high", "xhigh": "max"},
            max_output=131072,
            note="GLM-5.2 起支持 reasoning_effort，默认 max",
        ),
        ModelRule(
            pattern=r"glm-(4\.[5-9]|5(\.[0-9])?)(-.*)?",
            priority=50, as_of=AS_OF,
            thinking="toggle",
            thinking_param="thinking_type",
            max_output=131072,
            # 能力矩阵 v2.0：GLM 文本系列**不原生吃文档**，须先经文件解析服务转文本
            supports_vision=False,
            reject_documents=True,
            note="GLM-4.5/4.6/4.7/5.x 默认开启思考；文本系列不吃图/文档，需外部解析服务转文本",
        ),
        ModelRule(
            pattern=r"glm-4(\.[0-4])?(-.*)?",
            priority=40, as_of=AS_OF,
            thinking="unsupported",
            max_output=98304,
            supports_vision=False,
            reject_documents=True,
            note="GLM-4.5 以下不支持 thinking 对象；4.5 系列最大输出 96K",
        ),
    ),
)

KIMI = Profile(
    name="kimi",
    needs_reasoning_echo=True,
    max_output=16384,
    # 官方能力矩阵：k3 / k2.7 / k2.6 输入模态均含图与视频
    supports_vision=True,
    # 文档走独立的 `purpose=file-extract` 抽取通道，不在对话请求里内联附件
    reject_documents=True,
    model_rules=(
        ModelRule(
            pattern=r"kimi-k3(-.*)?",
            priority=100, as_of=AS_OF,
            thinking="always_on",
            thinking_param="reasoning_effort",
            effort_allowed=("low", "high", "max"),
            forbid_params=("thinking", "enable_thinking"),
            note="K3 始终思考，无 thinking 参数；默认 max；多轮须原样回传完整 assistant message",
        ),
        ModelRule(
            pattern=r"kimi-k2\.7-code",
            priority=95, as_of=AS_OF,
            thinking="always_on",
            thinking_param="thinking_type",
            # 官方：temperature 固定 1.0，传其他报错
            fixed_params={"temperature": 1.0, "top_p": 0.95},
            note="k2.7-code：temperature 锁 1.0、top_p 0.95、思考默认开启且关闭报错",
        ),
        ModelRule(
            pattern=r"kimi-k2\.6(-.*)?",
            priority=80, as_of=AS_OF,
            thinking="toggle",
            thinking_param="thinking_type",
            note="k2.6 默认开启思考、可关闭；支持保留式思考（开启时须回传推理块）",
        ),
        ModelRule(
            pattern=r"kimi-k2\.5(-.*)?",
            priority=80, as_of=AS_OF,
            thinking="toggle",
            thinking_param="thinking_type",
            # 官方：k2.5 不支持保留式思考（preserved thinking），无回传契约；发了只会引入噪声
            needs_reasoning_echo=False,
            note="k2.5 已于 2026-08-31 下线；规则保留只为让仍用旧名的调用方不至于匹配失败",
        ),
    ),
)

DEEPSEEK = Profile(
    name="deepseek",
    reasoning_keys=("reasoning_content",),
    needs_reasoning_echo=True,
    thinking_param="thinking_type",
    # 官方能力矩阵：**明确不支持文档 / PDF / Office**；整家不能内联附件
    reject_documents=True,
    # 默认按最保守算（V4-Pro 仅文本）；只有 flash 支持图像理解，由下方规则放开
    supports_vision=False,
    model_rules=(
        ModelRule(
            # 必须在 V4 规则之前命中：legacy reasoner 的契约与 V4 **相反** —— 入参带
            # reasoning_content 直接 400（官方多轮对话拼接一节明确要求剥离）
            pattern=r"deepseek-reasoner.*",
            priority=120, as_of=AS_OF,
            needs_reasoning_echo=False,
            supports_vision=False,
            note="legacy reasoner：2026-07-24 已弃用（按 flash 思考模式路由）；"
                 "入参含 reasoning_content → 400，必须剥离。规则保留以兼容旧调用方",
        ),
        ModelRule(
            pattern=r"deepseek-(v4-pro|reasoner).*",
            priority=100, as_of=AS_OF,
            effort_allowed=("low", "high", "max"),
            effort_map={"xhigh": "max"},
            # 官方：V4-Pro 输入模态"仅文本（不支持图像理解）"
            supports_vision=False,
            note="v4-pro：xhigh 映射为 max；默认 effort=high；仅文本，不吃图",
        ),
        ModelRule(
            # `deepseek-flash` 是 `deepseek-v4-flash` 的**改名**（V4.1-Flash），不是新模型；
            # 旧名同时保留 —— 厂商改名常见，删旧名会让存量配置直接匹配失败。
            pattern=r"deepseek-(v4-flash|flash).*",
            priority=100, as_of=AS_OF,
            effort_allowed=("low", "high"),
            effort_map={"xhigh": "high"},
            # 官方：全系仅 flash 支持图像理解（JPEG/PNG/GIF/WebP，单图 ≤ 32 MiB）
            supports_vision=True,
            note="v4-flash / flash（V4.1-Flash 改名）：xhigh 映射为 high；支持图像理解",
        ),
    ),
)

OPENAI = Profile(
    name="openai",
    require_usage_option=True,
    max_output=128000,
    supports_vision=True,
    # ⚠️ 只列 PDF：官方文件输入页明确「Chat Completions supports only .pdf
    # (application/pdf) for both file_data and file_id」；docx/xlsx/csv 等要走
    # Responses API 的 `input_file`，本内核的 openai_compat 走的是 Chat Completions。
    doc_mimes=("application/pdf",),
    max_file_mb=50,
    model_rules=(
        ModelRule(
            pattern=r"(gpt-5(\.[0-9])?.*|o[0-9].*)",
            priority=100, as_of=AS_OF,
            thinking_param="reasoning_effort",
            effort_allowed=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
            note="推理模型不支持修改 temperature（不报错但无效）",
        ),
        ModelRule(
            pattern=r"gpt-4(\.[0-9])?.*",
            priority=50, as_of=AS_OF,
            thinking="unsupported",
            note="非推理模型不支持 reasoning_effort",
        ),
    ),
)

ANTHROPIC = Profile(
    name="anthropic",
    needs_reasoning_echo=True,
    max_output=128000,
    supports_vision=True,
    # Messages API 的**内联** base64 文档块官方只支持 application/pdf；
    # 其他格式（docx/csv/txt/xlsx…）要走 Files API，本内核走内联，故只列 PDF。
    doc_mimes=("application/pdf",),
    # 取"单请求上限 32 MB"而非"Files API 单文件 500 MB"——内联 base64 会被请求体积卡死，
    # 拿 500 当闸门等于没闸门（官方文件上传页：单文件 500 MB 属 Files API 口径）。
    max_file_mb=32,
    model_rules=(
        ModelRule(
            # 必须排在 5 系 adaptive 规则之前：这两代在**任何情况**下都拒强制工具选择
            pattern=r"claude-(fable|mythos)-5\.1(-.*)?",
            priority=110, as_of=AS_OF,
            # 官方：这些模型上 type:"enabled" → 400，必须用 adaptive；budget_tokens 已废弃
            fixed_params={"thinking": {"type": "adaptive"}},
            forbid_params=("budget_tokens",),
            effort_allowed=("low", "medium", "high", "xhigh", "max"),
            reject_forced_tool=True,
            note="Fable5.1/Mythos5.1：必须 adaptive，且强制工具选择（any/tool）一律 400",
        ),
        ModelRule(
            pattern=r"claude-(opus-(4-7|4-8|5)|sonnet-5|fable-5|mythos-5)(-.*)?",
            priority=100, as_of=AS_OF,
            # 官方：这些模型上 type:"enabled" → 400，必须用 adaptive；budget_tokens 已废弃
            fixed_params={"thinking": {"type": "adaptive"}},
            forbid_params=("budget_tokens",),
            # 官方档位走 output_config.effort（见 anthropic.py 的 _EFFORTS）
            effort_allowed=("low", "medium", "high", "xhigh", "max"),
            note="Opus4.7/5、Sonnet5、Fable5、Mythos5：必须用 adaptive，budget_tokens → 400；"
                 "深度由 output_config.effort 控制",
        ),
        ModelRule(
            pattern=r"claude-(sonnet-4-5|opus-4-5|haiku-4-5)(-.*)?",
            priority=90, as_of=AS_OF,
            thinking="toggle",
            thinking_param="thinking_type",
            note="Sonnet4.5/Haiku4.5 及更早拒绝 adaptive，须用 budget_tokens；"
                 "Opus4.5 已不在在售阵容表，规则保留只为老账号仍可调用",
        ),
    ),
)

GEMINI = Profile(
    name="gemini",
    supports_vision=True,
    # 官方文档页：文档类型为 `application/pdf` 与 `text/plain`；
    # TXT / Markdown / HTML / XML 一律**仅作纯文本抽取**（图表与格式会丢）
    doc_mimes=("application/pdf", "text/plain"),
    max_file_mb=50,               # PDF ≤ 50 MB 或 ≤ 1000 页（取先到者）
    model_rules=(
        ModelRule(
            pattern=r"gemini-3(\.[0-9]+)?-pro.*",
            priority=100, as_of=AS_OF,
            thinking="always_on",
            thinking_api="level",
            effort_allowed=("low", "medium", "high"),
            forbid_params=("thinking_budget", "thinkingBudget"),
            note="3.x Pro：无法关闭思考，minimal 不支持（传了报错），默认 high",
        ),
        ModelRule(
            # 3.8+ Flash 起不接受 minimal（官方：will return an error），必须排在其上
            pattern=r"gemini-3\.[89](\d)?-flash.*",
            priority=90, as_of=AS_OF,
            thinking_api="level",
            effort_allowed=("low", "medium", "high"),
            forbid_params=("thinking_budget", "thinkingBudget"),
            note="3.8 Flash 起不支持 minimal thinking level（传了报错）",
        ),
        ModelRule(
            pattern=r"gemini-3(\.[0-9]+)?(-.*)?",
            priority=80, as_of=AS_OF,
            thinking_api="level",
            effort_allowed=("minimal", "low", "medium", "high"),
            forbid_params=("thinking_budget", "thinkingBudget"),
            note="Gemini 3 系列改用 thinkingConfig.thinkingLevel；与 thinkingBudget 同传 → 400",
        ),
        ModelRule(
            pattern=r"gemini-2\.5-flash-lite.*",
            priority=95, as_of=AS_OF,
            thinking="always_off",
            thinking_api="none",
            forbid_params=("thinking_level", "thinkingLevel"),
            note="2.5 Flash-Lite 模型本身不思考，下发思考参数无意义",
        ),
        ModelRule(
            pattern=r"gemini-2\.5(-.*)?",
            priority=70, as_of=AS_OF,
            thinking="toggle",
            thinking_api="budget",
            forbid_params=("thinking_level", "thinkingLevel"),
            note="2.5 系列用 thinkingConfig.thinkingBudget（0=关闭、-1=动态）；不支持 thinkingLevel",
        ),
    ),
)

QWEN = Profile(
    name="qwen",
    reasoning_keys=("reasoning_content",),
    thinking_param="enable_thinking",
    supports_vision=True,
    # 官方能力矩阵：上述模型原生只吃 文本 + 图片 + 视频（omni 另加音频），
    # **不直接接受文档** —— 文档走「文件问答」/「文档理解 API」两条独立通道。
    reject_documents=True,
    model_rules=(
        ModelRule(
            pattern=r".*-thinking(-.*)?",
            priority=100, as_of=AS_OF,
            thinking="always_on",
            note="带 -thinking 后缀为仅思考模型，无法关闭",
        ),
        ModelRule(
            pattern=r"qwen3\.8-omni-flash",
            priority=95, as_of=AS_OF,
            thinking_param="reasoning_effort",
            effort_allowed=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
            effort_map={"minimal": "low", "high": "xhigh", "max": "xhigh"},
            # 官方：reasoning_effort 与 thinking_budget 同时传会报错
            forbid_params=("thinking_budget",),
            note="qwen3.8-omni-flash 默认 xhigh；不可与 thinking_budget 同传",
        ),
        ModelRule(
            pattern=r".*omni-turbo.*",
            priority=90, as_of=AS_OF,
            thinking="unsupported",
            note="qwen-omni-turbo 已不在当前文档（现为 qwen3.8-omni-flash / qwen3.5-omni）；"
                 "规则保留以兼容旧调用方",
        ),
        ModelRule(
            pattern=r"qwen3-vl-(plus|flash)(-.*)?",
            priority=85, as_of=AS_OF,
            thinking="toggle",
            note="同为混合模型但默认 false（qwen3.x 文本系列默认 true）",
        ),
    ),
)

DOUBAO = Profile(
    name="doubao",
    thinking_param="thinking_type",
    supports_vision=True,
    # 模型页"文档理解"仅标 Supported，扩展名/大小/页数**未查到** ——
    # 既然连能吃什么都不知道，就不设闸门（gate 无声明即不拦），只如实记账。
    model_rules=(
        ModelRule(
            pattern=r"doubao-seed-2-1(-.*)?",
            priority=100, as_of=AS_OF,
            thinking_param="reasoning_effort",
            effort_allowed=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
            note="Seed 2.1 全系：thinking 开/关 + reasoning_effort 七档（默认 high）；"
                 "文+图+视频（无音频）",
        ),
        ModelRule(
            pattern=r"doubao-seed-character.*",
            priority=90, as_of=AS_OF,
            thinking="unsupported",
            note="不带深度思考标签的模型本身不支持，传 thinking 字段无意义",
        ),
    ),
)

HUNYUAN = Profile(
    name="hunyuan",
    thinking_param="thinking_type",
    stop_semantics="after",          # 官方：混元接口停在匹配内容之后（与 OpenAI 相反）
    supports_vision=True,
    # 官方：文档走**独立的文件上传 API**（csv/doc/docx/pdf/ppt/pptx/txt/xls/xlsx，
    # 单文件 ≤ 100 MB），不在对话请求里内联附件 → 内联附件在此拦掉。
    # 能吃的扩展名留在 note 里，供调用方走上传通道时参考。
    reject_documents=True,
    model_rules=(
        ModelRule(
            pattern=r"hunyuan-2\.0-instruct.*",
            priority=100, as_of=AS_OF,
            thinking="unsupported",
            max_output=16384,
            note="HY 2.0 Instruct 不支持深度思考",
        ),
        ModelRule(
            pattern=r"hy[0-9]-preview",
            priority=90, as_of=AS_OF,
            thinking="always_on",
            note="hy4-preview 默认开启深度思考",
        ),
    ),
)

GENERIC = Profile(
    name="generic",
    # 兜底档位：模型名可能任意（本机 ollama 拉什么是什么），能力矩阵无从谈起。
    # 标 False 后 `capability.py` 只记账不硬拦 —— 宁可放过，不可错杀。
    capabilities_known=False,
)

PROFILES = {
    "generic": GENERIC,
    "glm": GLM,
    "kimi": KIMI,
    "deepseek": DEEPSEEK,
    "openai": OPENAI,
    "anthropic": ANTHROPIC,
    "gemini": GEMINI,
    "qwen": QWEN,
    "doubao": DOUBAO,
    "hunyuan": HUNYUAN,
}

# 一级匹配的端点/域名特征（按顺序首个命中生效；显式 cfg.type 优先于此表）
DOMAIN_HINTS = (
    ("open.bigmodel.cn", "glm"),
    ("api.moonshot.cn", "kimi"),
    ("api.deepseek.com", "deepseek"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("dashscope.aliyuncs.com", "qwen"),
    ("maas.aliyuncs.com", "qwen"),
    ("volces.com", "doubao"),
    ("volcengineapi.com", "doubao"),
    ("hunyuan", "hunyuan"),
    ("tokenhub.tencentmaas.com", "hunyuan"),
)
