"""织语面：语料风格模块（设计 §6.5）。

不再独立生成完整回复，只产出「语料风格模块」注入 LLM：
- 通用要素解析：依人格卡 format_spec 给出格式约束（向人格引擎要要素类型）。
- 默认语料：用角色卡示例对话作为风格参照（语料替换/初始化路径留接口）。
- 兜底职责已移交 LLM：原本「答不了明说」话术不再由织语面产出，LLM 自行判断。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule


class WeaveFace(BaseFace):
    name = "weave"

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        p = ctx.persona
        # 一致性约束：<内心>与本句正文须同一主题、情绪一致——否则模型会把内心独白
        # 和对外正文生成成两段无关内容（实测出现内心「困惑」、正文却寒暄的脱节）。
        # 正文须重述内心而非逐字复读，否则「未说出口」的内心变成说出口的同一句。
        content = (f"【表达风格】按格式「{p.format_spec}」组织语言，"
                   f"保持{p.name}的口吻，与示例对话的语感一致。"
                   f"<内心>是本句未说出口的真实想法；正文须用自然口语把这份想法"
                   f"对用户说出来，与<内心>同一主题、情绪一致，不得逐字复读内心"
                   f"或另起无关话题。")
        return InjectionModule(
            source=self.name, content=content,
            fixed=False, priority=40,
        )
