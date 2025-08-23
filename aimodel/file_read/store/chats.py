from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from .base import chat_path, atomic_write, now_iso
from .index import load_index, save_index, refresh_index_after_change, ChatMeta

def _load_chat(session_id: str) -> Dict:
    p = chat_path(session_id)
    if not p.exists():
        return {"sessionId": session_id, "messages": [], "seq": 0, "summary": ""}  # add summary
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
        if "summary" not in data:
            data["summary"] = ""  # backfill older files
        return data
    
@dataclass
class ChatMessageRow:
    id: int
    sessionId: str
    role: str
    content: str
    createdAt: str

def upsert_on_first_message(session_id: str, title: str) -> ChatMeta:
    idx = load_index()
    existing = next((r for r in idx if r["sessionId"] == session_id), None)
    now = now_iso()
    if existing:
        if title and title.strip():
            existing["title"] = title.strip()
        existing["updatedAt"] = now
        save_index(idx)
        existing.setdefault("lastMessage", None)
        return ChatMeta(**existing)

    next_id = (max((r["id"] for r in idx), default=0) + 1) if idx else 1
    row = {
        "id": next_id,
        "sessionId": session_id,
        "title": (title.strip() or "New Chat"),
        "lastMessage": None,
        "createdAt": now,
        "updatedAt": now,
    }
    idx.append(row); save_index(idx)
    _save_chat(session_id, {"sessionId": session_id, "messages": [], "seq": 0, "summary": ""})
    return ChatMeta(**row)

def update_last(session_id: str, last_message: Optional[str], maybe_title: Optional[str]) -> ChatMeta:
    idx = load_index()
    row = next((r for r in idx if r["sessionId"] == session_id), None)
    if not row:
        raise ValueError(f"Unknown sessionId: {session_id}")
    if last_message is not None:
        row["lastMessage"] = last_message
    if maybe_title and maybe_title.strip():
        row["title"] = maybe_title.strip()
    row["updatedAt"] = now_iso()
    save_index(idx)
    row.setdefault("lastMessage", None)
    return ChatMeta(**row)

def append_message(session_id: str, role: str, content: str) -> ChatMessageRow:
    data = _load_chat(session_id)
    seq = int(data.get("seq", 0)) + 1
    msg = {
        "id": seq, "sessionId": session_id, "role": role,
        "content": content, "createdAt": now_iso(),
    }
    data["messages"].append(msg); data["seq"] = seq
    _save_chat(session_id, data)

    idx = load_index()
    row = next((r for r in idx if r["sessionId"] == session_id), None)
    if row:
        row["updatedAt"] = msg["createdAt"]
        if role == "assistant":
            row["lastMessage"] = content
        save_index(idx)

    # pending ops are applied by pending.apply_pending_for() from the router after appends
    return ChatMessageRow(**msg)

def delete_message(session_id: str, message_id: int) -> int:
    data = _load_chat(session_id)
    msgs = data.get("messages", [])
    before = len(msgs)
    msgs = [m for m in msgs if int(m.get("id", -1)) != int(message_id)]
    if len(msgs) == before:
        return 0
    data["messages"] = msgs
    _save_chat(session_id, data)
    refresh_index_after_change(session_id, msgs)
    return 1

def delete_messages_batch(session_id: str, message_ids: List[int]) -> List[int]:
    wanted = {int(i) for i in (message_ids or [])}
    if not wanted:
        return []
    data = _load_chat(session_id)
    msgs = data.get("messages", [])
    keep, deleted = [], []
    for m in msgs:
        mid = int(m.get("id", -1))
        if mid in wanted:
            deleted.append(mid)
        else:
            keep.append(m)
    if not deleted:
        return []
    data["messages"] = keep
    _save_chat(session_id, data)
    refresh_index_after_change(session_id, keep)
    return deleted

def list_messages(session_id: str) -> List[ChatMessageRow]:
    data = _load_chat(session_id)
    return [ChatMessageRow(**m) for m in data.get("messages", [])]

def list_paged(page: int, size: int, ceiling_iso: Optional[str]) -> Tuple[List[ChatMeta], int, int, bool]:
    rows = load_index()
    rows.sort(key=lambda r: r["updatedAt"], reverse=True)
    if ceiling_iso:
        rows = [r for r in rows if r["updatedAt"] <= ceiling_iso]

    total = len(rows)
    size = max(1, min(100, int(size)))
    page = max(0, int(page))

    start = page * size
    end = start + size

    page_rows = rows[start:end]
    total_pages = (total + size - 1) // size if total else 1
    last_flag = end >= total

    metas = []
    for r in page_rows:
        r.setdefault("lastMessage", None)
        metas.append(ChatMeta(**r))
    return metas, total, total_pages, last_flag

def delete_batch(session_ids: List[str]) -> List[str]:
    for sid in session_ids:
        try: chat_path(sid).unlink(missing_ok=True)
        except Exception: pass
    idx = load_index()
    keep = [r for r in idx if r["sessionId"] not in set(session_ids)]
    save_index(keep)
    return session_ids

def merge_chat(source_id: str, target_id: str):
    source_msgs = list_messages(source_id)
    target_msgs = list_messages(target_id)

    # Insert source first, then re-add target to preserve order
    merged = []
    for m in source_msgs:
        row = append_message(target_id, m.role, m.content)
        merged.append(row)

    for m in target_msgs:
        row = append_message(target_id, m.role, m.content)
        merged.append(row)

    return merged

def _save_chat(session_id: str, data: Dict):
    atomic_write(chat_path(session_id), data)

def set_summary(session_id: str, new_summary: str) -> None:
    data = _load_chat(session_id)
    data["summary"] = new_summary or ""
    _save_chat(session_id, data)

def get_summary(session_id: str) -> str:
    data = _load_chat(session_id)
    return str(data.get("summary") or "")

def merge_chat_new(source_id: str, target_id: Optional[str] = None):
    from uuid import uuid4
    new_id = str(uuid4())
    upsert_on_first_message(new_id, "Merged Chat")

    merged = []

    # source first
    for m in list_messages(source_id):
        row = append_message(new_id, m.role, m.content)
        merged.append(row)

    # then target (if exists)
    if target_id:
        for m in list_messages(target_id):
            row = append_message(new_id, m.role, m.content)
            merged.append(row)

    return new_id, merged

def edit_message(session_id: str, message_id: int, new_content: str) -> Optional[ChatMessageRow]:
    data = _load_chat(session_id)
    msgs = data.get("messages", [])
    updated = None

    for m in msgs:
        if int(m.get("id", -1)) == int(message_id):
            m["content"] = new_content
            m["updatedAt"] = now_iso()
            updated = m
            break

    if not updated:
        return None

    _save_chat(session_id, data)

    # refresh index if last message changed
    refresh_index_after_change(session_id, msgs)

    return ChatMessageRow(**updated)


# expose internals for pending ops
__all__ = [
    "ChatMessageRow",
    "upsert_on_first_message", "update_last", "append_message",
    "delete_message", "delete_messages_batch", "list_messages",
    "list_paged", "delete_batch", "merge_chat", "merge_chat_new",
    "_load_chat", "_save_chat", "edit_message", "set_summary", "get_summary", 
]
