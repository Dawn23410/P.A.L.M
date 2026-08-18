"""意图路由 —— 判断用户输入应走 Boss 直答还是启动 Worker。

路由分类：
- "chat"：闲聊 / 简单问答 → Boss 直接回复，不启动 Worker
- "task"：复杂任务（需多步工具调用） → Boss 回复确认 + 后台启动 Worker
- "intervention"：干预指令（针对活跃 Worker） → 转发到 Worker 干预队列
- "query"：查询 Worker 进展 → Boss 从 trace_store 检索后回复

路由策略：
1. 纯关键词匹配（初期方案，零 LLM 调用，延迟 <1ms）
2. 后续可升级为 flash_model 语义分析（关键词无法覆盖时兜底）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# 意图类型
I_CHAT = "chat"
I_TASK = "task"
I_INTERVENTION = "intervention"
I_QUERY = "query"


@dataclass
class IntentResult:
    """意图路由结果。"""

    intent: str = I_CHAT
    task_goal: str = ""               # task 模式：Worker 要执行的任务目标
    intervention_action: str = ""      # intervention 模式：cancel/pause/resume/redirect
    redirect_instruction: str = ""     # redirect 时的新的任务指令
    confidence: float = 1.0            # 置信度（关键词匹配 = 1.0，LLM 分析 < 1.0）


# ── 关键词规则表 ──────────────────────────────────────────────

# 任务触发词：匹配到则判定为 task（需启动 Worker）
_TASK_PATTERNS = [
    r"(?:帮我|请|麻烦|可以|能不能|你给我).{0,4}(?:做|搞|弄|写|改|查|找|部署|分析|整理|搜索|构建|开发|测试|优化|修复|迁移|搭建|配置|安装|生成|创建|删除|清理|检查|排查|诊断)",
    r"(?:写一个|写段|写个|做个|做个|帮我写|帮我查|帮我找|帮我改|帮我分|帮我整|帮我排|帮我搭)",
    r"(?:运行|执行|启动|调用).{0,6}(?:脚本|程序|代码|命令|任务)",
    r"(?:分析|研究|调研|对比|评估|审查).{0,6}(?:一下|看下|看看)",
]

# 干预触发词：匹配到则判定为 intervention
_INTERVENTION_PATTERNS = {
    "cancel": [
        r"(?:别做了|不用了|取消|算了|停下|停止|终止|放弃|别弄了|别搞了|不需要了)",
    ],
    "pause": [
        r"(?:暂停|停一下|等一下|先别|先停|hold\s*on|pause)",
    ],
    "resume": [
        r"(?:继续|接着|恢复|go\s*on|resume|继续做|接着干)",
    ],
    "redirect": [
        r"(?:换个方向|换个思路|不要这样做|改成|改为|换个方式|重新来|换个方法)",
    ],
}

# 查询触发词：匹配到则判定为 query
_QUERY_PATTERNS = [
    r"(?:进度|怎么样了|在做什么|什么状态|做到哪了|好了吗|完成了吗|还在跑吗|跑完了吗)",
    r"(?:worker|后台|任务).{0,4}(?:状态|进度|情况)",
]

# 编译正则
_TASK_RE = [re.compile(p, re.IGNORECASE) for p in _TASK_PATTERNS]
_QUERY_RE = [re.compile(p, re.IGNORECASE) for p in _QUERY_PATTERNS]
_INTERVENTION_RE = {
    action: [re.compile(p, re.IGNORECASE) for p in patterns]
    for action, patterns in _INTERVENTION_PATTERNS.items()
}


class IntentRouter:
    """意图路由器：纯关键词匹配，零 LLM 调用。

    worker_active 参数由 coordinator 传入，表示当前是否有活跃的 Worker。
    无活跃 Worker 时，intervention 和 query 意图降级为 chat。
    """

    def route(self, message: str, worker_active: bool = False) -> IntentResult:
        """路由用户消息，返回意图判定结果。"""
        msg = message.strip()
        if not msg:
            return IntentResult(intent=I_CHAT)

        # 优先级 1：干预指令（仅在有活跃 Worker 时生效）
        if worker_active:
            for action, patterns in _INTERVENTION_RE.items():
                for pat in patterns:
                    if pat.search(msg):
                        result = IntentResult(
                            intent=I_INTERVENTION,
                            intervention_action=action,
                        )
                        if action == "redirect":
                            # 尝试提取重定向指令（触发词之后的内容）
                            result.redirect_instruction = self._extract_redirect(msg)
                        return result

            # 优先级 2：查询 Worker 进展
            for pat in _QUERY_RE:
                if pat.search(msg):
                    return IntentResult(intent=I_QUERY)

        # 优先级 3：任务触发
        for pat in _TASK_RE:
            if pat.search(msg):
                return IntentResult(
                    intent=I_TASK,
                    task_goal=msg,  # 整条消息作为任务目标
                )

        # 默认：闲聊
        return IntentResult(intent=I_CHAT)

    @staticmethod
    def _extract_redirect(message: str) -> str:
        """从重定向指令中提取新的任务描述。

        策略：去掉触发词前缀，保留剩余内容作为新指令。
        如果没有剩余内容，返回空串（coordinator 会让 Boss 追问）。
        """
        # 去掉常见触发词前缀
        cleaned = re.sub(
            r"^(?:换个方向|换个思路|不要这样做|改成|改为|换个方式|重新来|换个方法)[：:，,]?\s*",
            "", message, flags=re.IGNORECASE,
        )
        return cleaned.strip() if cleaned.strip() != message.strip() else ""

    def route_with_llm(
        self,
        message: str,
        llm_fn,
        model: str,
        worker_active: bool = False,
    ) -> IntentResult:
        """LLM 语义分析兜底（关键词匹配不确定时调用）。

        当前保留接口但未启用：关键词匹配已覆盖常见场景。
        后续如遇关键词无法覆盖的边界 case，可激活此路径。
        """
        # TODO: 用 flash_model 做轻量意图分类
        # 当前直接回退关键词匹配
        return self.route(message, worker_active)
