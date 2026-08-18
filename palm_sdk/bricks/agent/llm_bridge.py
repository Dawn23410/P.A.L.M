async def stream_llm(*_args, **_kwargs):
    # 独立态无 LLM 后端；调用方应已做可用性守卫。
    raise RuntimeError("独立态未接入 LLM 后端")
