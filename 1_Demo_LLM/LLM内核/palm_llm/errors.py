"""内核统一异常层级 —— 把「出错」从一句 RuntimeError 变成可分类、可决策的信号。

为什么要分类而不是继续抛 RuntimeError
--------------------------------------
调用方（尤其是"自动规划 / 连续调用"这类无人值守路径）需要**据错决策**：
能不能重试、要不要等、是不是该换 provider。一句裸 RuntimeError 里没有这些信息，
调用方只能靠字符串匹配猜，必然腐烂。故把错误拆成有限几类，每类只回答一个问题：
**这次失败值不值得再试一次？**

兼容契约（重要）
----------------
`PalmLLMError` 继承 `RuntimeError`。历史调用方与测试都用 `except RuntimeError`
兜底，换层级**不能把它们的兜底打穿** —— 所以这里是"更细的分类"，不是"新的体系"。
文案一律由调用方给定（各家错误体形态不同，内核不做统一改写），内核只负责选类型。

`retryable` 是安全侧标记：**默认 False**，只有明确"再来一次可能成功"的类别才置真。
"""
from __future__ import annotations

from typing import Optional


class PalmLLMError(RuntimeError):
    """内核全部异常的基类（继承 RuntimeError 以兼容既有兜底）。"""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
        request_id: Optional[str] = None,
        text: Optional[str] = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status = status
        self.retry_after = retry_after          # 秒；来自 Retry-After 头/错误体
        self.request_id = request_id
        self.text = text                        # 上游原始错误文本（已截断）


class TransportError(PalmLLMError):
    """传输层失败（连接重置 / 各类超时 / DNS / 首字节超时）—— 可重试。"""

    retryable = True


class UpstreamServerError(PalmLLMError):
    """上游 5xx —— 可重试，但**必须有界**（故障期无限重试只会放大损失）。"""

    retryable = True


class RateLimitError(PalmLLMError):
    """429 限流 —— 可重试，且**必须尊重 `Retry-After`**（不尊重就是继续被打）。"""

    retryable = True


class AuthError(PalmLLMError):
    """401 / 403 鉴权或权限不足 —— 不可重试（换连接也过不了鉴权）。"""


class BadRequestError(PalmLLMError):
    """4xx 参数 / 语义错误 —— 不可重试（字段超集问题由降级通道另行处理）。"""


class NotConfiguredError(PalmLLMError):
    """本地配置缺失（如未填 API Key）—— 不可重试，且应指导调用方去补配置。"""


class StreamInterruptedError(PalmLLMError):
    """**已向调用方产出内容后**中断 —— 绝不重试。

    重试意味着重新生成整段内容，对调用方是重复输出、对计费是重复扣费。
    正确做法是把已产出的部分交出去并显式标记"未完成"，由上层决定是否让用户重发。
    """


class CapabilityError(PalmLLMError):
    """输入超出目标模型能力 —— 在**发请求之前**拦截，未产生任何网络往返。"""


def error_for_status(
    status: int,
    message: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    text: Optional[str] = None,
    retry_after: Optional[float] = None,
) -> PalmLLMError:
    """按 HTTP 状态码选类型；`message` 由调用方给定（保留各家可读文案）。"""
    if status == 429:
        cls = RateLimitError
    elif status in (401, 403):
        cls = AuthError
    elif 400 <= status < 500:
        cls = BadRequestError
    elif status >= 500:
        cls = UpstreamServerError
    else:
        cls = PalmLLMError
    return cls(message, provider=provider, model=model, status=status,
               text=text, retry_after=retry_after)


def error_for_transport(
    exc: Optional[BaseException],
    message: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    interrupted: bool = False,
) -> PalmLLMError:
    """传输层异常 → 类型化错误。

    `interrupted=True` 表示"已产出内容后才断"，一律归为 `StreamInterruptedError`
    （不可重试），而不是可重试的 `TransportError` —— 这个区分是防重复生成的关键。
    """
    if interrupted:
        return StreamInterruptedError(message, provider=provider, model=model)
    return TransportError(message, provider=provider, model=model)


__all__ = [
    "PalmLLMError",
    "TransportError",
    "UpstreamServerError",
    "RateLimitError",
    "AuthError",
    "BadRequestError",
    "NotConfiguredError",
    "StreamInterruptedError",
    "CapabilityError",
    "error_for_status",
    "error_for_transport",
]
