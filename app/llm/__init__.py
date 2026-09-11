r"""P.A.L.M -> palm_llm 桥接层（薄适配器）。

`llm` 微内核已抽离为主目录下的内嵌独立项目 `palm-llm/`（palm-llm/palm_llm），
由 `palm_boot` 自动挂载进 sys.path —— 无需 pip install、不依赖兄弟目录位置。
本文件及子模块仅做再导出，确保历史 `from llm.xxx import ...` 写法继续可用；
真实实现全部在 `palm_llm` 中，P.A.L.M 不再内嵌该模块源码。
"""
import palm_boot  # noqa: F401  自举：挂载 palm-llm/ 等内嵌项目

# 再导出公共 API（兼容旧 `from llm import ...`）
# 注：原生 Anthropic/Gemini/Mock 适配已移除，协议统一为 OpenAI 兼容（openai_compat）。
from palm_llm import (  # noqa: E402,F401
    BaseProvider,
    Message,
    ModelParameters,
    OpenAICompatProvider,
    ProviderConfig,
    Tool,
    get_provider_instance,
)
