from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class MergeChatReq(BaseModel):
    sourceId: str
    targetId: Optional[str] = None
    newChat: bool = False

class ChatMetaModel(BaseModel):
    id: int
    sessionId: str
    title: str
    lastMessage: Optional[str] = None
    createdAt: str
    updatedAt: str

class PageResp(BaseModel):
    content: List[ChatMetaModel]
    totalElements: int
    totalPages: int
    size: int
    number: int
    first: bool
    last: bool
    empty: bool

class BatchMsgDeleteReq(BaseModel):
    messageIds: List[int]

class BatchDeleteReq(BaseModel):
    sessionIds: List[str]

class EditMessageReq(BaseModel):
    messageId: int
    content: str    

class ChatBody(BaseModel):
    sessionId: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None
    max_tokens: Optional[int] = 512
    temperature: float = 0.7
    top_p: float = 0.95
    # NEW:
    autoWeb: bool = True
    webK: int = 3