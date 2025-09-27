from pydantic import BaseModel, Field

from ..core.logging import get_logger

log = get_logger(__name__)


class SearchReq(BaseModel):
    query: str
    sessionId: str | None = None
    kChat: int = 6
    kGlobal: int = 4
    hybrid_alpha: float = 0.5


class ItemRow(BaseModel):
    id: str
    sessionId: str | None
    source: str
    title: str | None
    mime: str | None
    size: int | None
    createdAt: str
    meta: dict[str, str] = Field(default_factory=dict)


class SearchHit(BaseModel):
    id: str
    text: str
    score: float
    source: str | None = None
    title: str | None = None
    sessionId: str | None = None
    url: str | None = None
