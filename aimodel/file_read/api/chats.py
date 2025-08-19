from __future__ import annotations
from dataclasses import asdict
from typing import List, Optional, Dict
from ..store import apply_pending_for

from fastapi import APIRouter
from pydantic import BaseModel

from ..store import (
    upsert_on_first_message,
    update_last as store_update_last,
    list_messages as store_list_messages,
    list_paged as store_list_paged,
    append_message as store_append,
    delete_batch as store_delete_batch,
    delete_message as store_delete_message,
    delete_messages_batch as store_delete_messages_batch,
    enqueue_pending,  # generic queue op
)

router = APIRouter()

# ---------- Models ----------
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

class PendingDeleteReq(BaseModel):
    messageIds: Optional[List[int]] = None
    tailAssistant: Optional[bool] = False

class QueueOpReq(BaseModel):
    type: str                       # e.g., "deleteMessages"
    payload: Dict[str, object] = {} # op-specific payload

class QueueDeleteReq(BaseModel):
    messageIds: Optional[List[int]] = None
    tailAssistant: Optional[bool] = False

class BatchDeleteReq(BaseModel):
    sessionIds: List[str]

# ---------- Routes ----------
@router.post("/api/chats")
async def api_create_chat(body: Dict[str, str]):
    session_id = (body.get("sessionId") or "").strip()
    title = (body.get("title") or "").strip()
    if not session_id:
        return {"error": "sessionId required"}
    row = upsert_on_first_message(session_id, title or "New Chat")
    return asdict(row)

@router.put("/api/chats/{session_id}/last")
async def api_update_last(session_id: str, body: Dict[str, str]):
    last_message = body.get("lastMessage")
    title = body.get("title")
    row = store_update_last(session_id, last_message, title)
    return asdict(row)

# Keep this BEFORE the {message_id} route
@router.delete("/api/chats/{session_id}/messages/batch")
async def api_delete_messages_batch(session_id: str, req: BatchMsgDeleteReq):
    deleted = store_delete_messages_batch(session_id, req.messageIds or [])
    # return numbers, not strings
    return {"deleted": deleted}

@router.delete("/api/chats/{session_id}/messages/{message_id}")
async def api_delete_message(session_id: str, message_id: int):
    deleted = store_delete_message(session_id, int(message_id))
    return {"deleted": deleted}

# Back-compat convenience (legacy) — OK to keep if you still call it
@router.post("/api/chats/{session_id}/messages/pending-delete")
async def api_pending_delete(session_id: str, req: PendingDeleteReq):
    enqueue_pending(session_id, "deleteMessages", {
        "messageIds": [int(i) for i in (req.messageIds or [])],
        "tailAssistant": bool(req.tailAssistant or False),
    })
    return {"queued": True}

@router.get("/api/chats/paged", response_model=PageResp)
async def api_list_paged(page: int = 0, size: int = 30, ceiling: Optional[str] = None):
    rows, total, total_pages, last_flag = store_list_paged(page, size, ceiling)
    content = [ChatMetaModel(**asdict(r)) for r in rows]
    return PageResp(
        content=content,
        totalElements=total,
        totalPages=total_pages,
        size=size,
        number=page,
        first=(page == 0),
        last=last_flag,
        empty=(len(content) == 0),
    )

@router.get("/api/chats/{session_id}/messages")
async def api_list_messages(session_id: str):
    rows = store_list_messages(session_id)
    return [asdict(r) for r in rows]

@router.post("/api/chats/{session_id}/messages")
async def api_append_message(session_id: str, body: Dict[str, str]):
    role = (body.get("role") or "user").strip()
    content = (body.get("content") or "").rstrip()
    row = store_append(session_id, role, content)

    # ← NEW: run pending ops now that this message is persisted
    try:
        apply_pending_for(session_id)
    except Exception:
        pass

    return asdict(row)

@router.delete("/api/chats/batch")
async def api_delete_batch(req: BatchDeleteReq):
    deleted = store_delete_batch(req.sessionIds or [])
    return {"deleted": deleted}

# ---------- Generic queue API ----------
@router.post("/api/chats/{session_id}/queue-op")
async def api_queue_op(session_id: str, req: QueueOpReq):
    enqueue_pending(session_id, req.type, req.payload or {})
    return {"queued": True}

@router.post("/api/chats/{session_id}/messages/queue-delete")
async def api_queue_delete(session_id: str, req: QueueDeleteReq):
    enqueue_pending(session_id, "deleteMessages", {
        "messageIds": [int(i) for i in (req.messageIds or [])],
        "tailAssistant": bool(req.tailAssistant or False),
    })
    return {"queued": True}
