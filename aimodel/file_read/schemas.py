from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ChatBody(BaseModel):
    sessionId: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None
    max_tokens: Optional[int] = 512
    temperature: float = 0.7
    top_p: float = 0.95
