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
        content = (f"【表达风格】按格式「{p.format_spec}」组织语言，"
                   f"保持{p.name}的口吻，与示例对话的语感一致。")
        return InjectionModule(
            source=self.name, content=content,
            fixed=False, priority=40,
        )
