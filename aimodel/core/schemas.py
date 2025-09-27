# core/schemas.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..core.logging import get_logger

log = get_logger(__name__)


class Attachment(BaseModel):
    name: str
    source: str | None = None
    sessionId: str | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    attachments: list[Attachment] | None = None


class ChatMetaModel(BaseModel):
    id: int
    sessionId: str
    title: str
    lastMessage: str | None = None
    createdAt: str
    updatedAt: str
    ownerUid: str | None = None
    ownerEmail: str | None = None


class PageResp(BaseModel):
    content: list[ChatMetaModel]
    totalElements: int
    totalPages: int
    size: int
    number: int
    first: bool
    last: bool
    empty: bool


class BatchMsgDeleteReq(BaseModel):
    messageIds: list[int]


class BatchDeleteReq(BaseModel):
    sessionIds: list[str]


class EditMessageReq(BaseModel):
    messageId: int
    content: str


class ChatBody(BaseModel):
    sessionId: str | None = None
    messages: list[ChatMessage] | None = None

    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None

    autoWeb: bool | None = None
    webK: int | None = None
    autoRag: bool | None = None
