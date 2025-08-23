from __future__ import annotations
from dataclasses import asdict
from typing import List, Optional, Dict
from .. import retitle_worker

from fastapi import APIRouter
from pydantic import BaseModel
from ..retitle_worker import enqueue as enqueue_retitle

from ..core.schemas import (
    ChatMetaModel,
    PageResp,
    BatchMsgDeleteReq,
    BatchDeleteReq,
    MergeChatReq,
    EditMessageReq
)

from ..store import (
    upsert_on_first_message,
    update_last as store_update_last,
    list_messages as store_list_messages,
    list_paged as store_list_paged,
    append_message as store_append,
    delete_batch as store_delete_batch,
    delete_message as store_delete_message,
    delete_messages_batch as store_delete_messages_batch,
    merge_chat as store_merge_chat,
    merge_chat_new as store_merge_chat_new,
    edit_message as edit_message
)

router = APIRouter()

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



@router.delete("/api/chats/{session_id}/messages/batch")
async def api_delete_messages_batch(session_id: str, req: BatchMsgDeleteReq):
    deleted = store_delete_messages_batch(session_id, req.messageIds or [])
    return {"deleted": deleted}

@router.delete("/api/chats/{session_id}/messages/{message_id}")
async def api_delete_message(session_id: str, message_id: int):
    deleted = store_delete_message(session_id, int(message_id))
    return {"deleted": deleted}

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
    return asdict(row)

@router.delete("/api/chats/batch")
async def api_delete_batch(req: BatchDeleteReq):
    deleted = store_delete_batch(req.sessionIds or [])
    return {"deleted": deleted}

@router.post("/api/chats/merge")
async def api_merge_chat(req: MergeChatReq):
    if req.newChat:
        new_id, merged = store_merge_chat_new(req.sourceId, req.targetId)
        return {
            "newChatId": new_id,
            "mergedCount": len(merged),
        }
    else:
        merged = store_merge_chat(req.sourceId, req.targetId)
        return {"mergedCount": len(merged)}


@router.put("/api/chats/{session_id}/messages/{message_id}")
async def api_edit_message(session_id: str, message_id: int, req: EditMessageReq):
    row = edit_message(session_id, message_id, req.content)
    if not row:
        return {"error": "Message not found"}
    return asdict(row)


@router.post("/api/chats/{session_id}/messages")
async def api_append_message(session_id: str, body: Dict[str, str]):
    role = (body.get("role") or "user").strip()
    content = (body.get("content") or "").rstrip()
    row = store_append(session_id, role, content)

    # 🚀 Background retitle trigger
    if role == "user":
        # get all messages in this session (lightweight index only)
        msgs = store_list_messages(session_id)
        enqueue_retitle(session_id, [asdict(m) for m in msgs])

    return asdict(row)