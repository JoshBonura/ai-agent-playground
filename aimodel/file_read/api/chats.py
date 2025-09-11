# ===== aimodel/file_read/api/chats.py =====
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from ..core.logging import get_logger
from ..core.schemas import (BatchDeleteReq, BatchMsgDeleteReq, ChatMessage,
                            ChatMetaModel, EditMessageReq, PageResp)
from ..deps.auth_deps import require_auth
from ..store import chats as store
from ..store.base import user_root
from ..utils.streaming import strip_runjson

# retitle worker is optional
try:
    from ..workers.retitle_worker import \
        enqueue as enqueue_retitle  # type: ignore
except Exception:  # pragma: no cover
    enqueue_retitle = None  # type: ignore

log = get_logger(__name__)
router = APIRouter()


def _is_admin(user) -> bool:
    import os

    admins = {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS", "").split(","))}
    return (user.get("email") or "").lower() in admins


@router.post("/api/chats")
async def api_create_chat(body: dict[str, str], user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    email = (user.get("email") or "").lower()
    root = user_root(uid)

    session_id = (body.get("sessionId") or "").strip()
    title = (body.get("title") or "").strip() or "New Chat"

    row = store.upsert_on_first_message(root, uid, email, session_id, title)
    return asdict(row)


@router.put("/api/chats/{session_id}/last")
async def api_update_last(session_id: str, body: dict[str, str], user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)

    last_message = body.get("lastMessage")
    title = body.get("title")
    row = store.update_last(root, uid, session_id, last_message, title)
    return asdict(row)


@router.get("/api/chats/paged", response_model=PageResp)
async def api_list_paged(
    page: int = 0,
    size: int = 30,
    ceiling: str | None = None,
    user=Depends(require_auth),
):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)

    rows, total, total_pages, last_flag = store.list_paged(root, uid, page, size, ceiling)
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
async def api_list_messages(session_id: str, user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    rows = store.list_messages(root, uid, session_id)
    return [asdict(r) for r in rows]


@router.post("/api/chats/{session_id}/messages")
async def api_append_message(session_id: str, msg: ChatMessage, user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)

    role = msg.role
    content = (msg.content or "").rstrip()
    attachments = msg.attachments or []

    row = store.append_message(root, uid, session_id, role, content, attachments=attachments)

    # queue retitle opportunistically
    if role == "assistant" and enqueue_retitle:
        try:
            msgs = store.list_messages(root, uid, session_id)
            last_seq = max((int(m.id) for m in msgs), default=0)
            msgs_clean = []
            for m in msgs:
                dm = asdict(m)
                dm["content"] = strip_runjson(dm.get("content") or "")
                msgs_clean.append(dm)
                enqueue_retitle(root, uid, session_id, msgs_clean, job_seq=last_seq)
        except Exception as e:  # best-effort
            log.debug(f"[retitle] enqueue failed for {session_id}: {e!r}")

    return asdict(row)


@router.delete("/api/chats/{session_id}/messages/{message_id}")
async def api_delete_message(session_id: str, message_id: int, user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    deleted = store.delete_message(root, uid, session_id, int(message_id))
    return {"deleted": deleted}


@router.delete("/api/chats/{session_id}/messages/batch")
async def api_delete_messages_batch(
    session_id: str, req: BatchMsgDeleteReq, user=Depends(require_auth)
):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    deleted = store.delete_messages_batch(root, uid, session_id, req.messageIds or [])
    return {"deleted": deleted}


@router.delete("/api/chats/batch")
async def api_delete_batch(req: BatchDeleteReq, user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    deleted = store.delete_batch(root, uid, req.sessionIds or [])
    return {"deleted": deleted}


@router.put("/api/chats/{session_id}/messages/{message_id}")
async def api_edit_message(
    session_id: str, message_id: int, req: EditMessageReq, user=Depends(require_auth)
):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    row = store.edit_message(root, uid, session_id, message_id, req.content)
    if not row:
        return {"error": "Message not found"}
    return asdict(row)
