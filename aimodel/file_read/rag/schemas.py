from pydantic import BaseModel, Field
from typing import Optional, Dict

class SearchReq(BaseModel):
    query: str
    sessionId: Optional[str] = None
    kChat: int = 6
    kGlobal: int = 4
    hybrid_alpha: float = 0.5  

class ItemRow(BaseModel):
    id: str
    sessionId: Optional[str]
    source: str
    title: Optional[str]
    mime: Optional[str]
    size: Optional[int]
    createdAt: str
    meta: Dict[str, str] = Field(default_factory=dict)

class SearchHit(BaseModel):
    id: str
    text: str
    score: float
    source: Optional[str] = None   
    title: Optional[str] = None
    sessionId: Optional[str] = None
    url: Optional[str] = None