try:
    from pydantic import BaseModel

    class ChatMessage(BaseModel):
        role: str = "user"
        content: str = ""
        reasoning: str | None = None
        name: str | None = None
        tool_calls: list[dict] | None = None
        tool_call_id: str | None = None
        images: list[dict] | None = None
        attachments: list[dict] | None = None

    class ChatRequest(BaseModel):
        messages: list[ChatMessage] = []
        model: str = ""
        provider: dict | None = None
        temperature: float | None = None
        max_tokens: int | None = None
        thinking: dict | None = None

    class ConversationLogList(BaseModel):
        items: list = []

    class DiscoverRequest(BaseModel):
        provider: str = ""
        base_url: str = ""

    class ProviderRef(BaseModel):
        id: str = ""
        name: str = ""
except Exception:  # pydantic 未装时退化为普通对象
    class ChatMessage:
        def __init__(self, role="user", content=""):
            self.role = role
            self.content = content

    class ChatRequest:
        def __init__(self, messages=None, model="", provider=None,
                     temperature=None, max_tokens=None, thinking=None):
            self.messages = messages or []
            self.model = model
            self.provider = provider
            self.temperature = temperature
            self.max_tokens = max_tokens
            self.thinking = thinking

    class ConversationLogList:
        def __init__(self, items=None):
            self.items = items or []

    class DiscoverRequest:
        def __init__(self, provider="", base_url=""):
            self.provider = provider
            self.base_url = base_url

    class ProviderRef:
        def __init__(self, id="", name=""):
            self.id = id
            self.name = name
