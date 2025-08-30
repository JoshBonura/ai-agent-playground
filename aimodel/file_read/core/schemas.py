# core/schemas.py
from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel


class Attachment(BaseModel):
    name: str
    source: Optional[str] = None
    sessionId: Optional[str] = None

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    attachments: Optional[List[Attachment]] = None  # ✅ new

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

    # ↓ make optional; defaults come from effective settings
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None

    # ↓ also optional; defaults come from settings
    autoWeb: Optional[bool] = None
    webK: Optional[int] = None
    autoRag: Optional[bool] = None   
