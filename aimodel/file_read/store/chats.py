from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..rag.store import delete_namespace as rag_delete_namespace
from .base import (atomic_write_encrypted, chat_path, now_iso,
                   read_json_encrypted)
from .index import ChatMeta, load_index, refresh_index_after_change, save_index

log = get_logger(__name__)


def _load_chat(root: Path, uid: str, session_id: str) -> dict[str, Any]:
    p = chat_path(root, session_id)
    if not p.exists():
        return {"sessionId": session_id, "messages": [], "seq": 0, "summary": "", "ownerUid": uid}
    return read_json_encrypted(uid, root, p)


@dataclass
class ChatMessageRow:
    id: int
    sessionId: str
    role: str
    content: str
    createdAt: str
    attachments: list[dict] | None = None


def _normalize_attachments(atts: list[Any] | None) -> list[dict] | None:
    if not atts:
        return None
    out: list[dict] = []
    for a in atts:
        if isinstance(a, dict):
            out.append(
                {"name": a.get("name"), "source": a.get("source"), "sessionId": a.get("sessionId")}
            )
        else:
            try:
                out.append(
                    {
                        "name": getattr(a, "name", None),
                        "source": getattr(a, "source", None),
                        "sessionId": getattr(a, "sessionId", None),
                    }
                )
            except Exception:
                continue
    return out or None


def upsert_on_first_message(
    root: Path, uid: str, email: str, session_id: str, title: str
) -> ChatMeta:
    idx = load_index(root, uid)
    existing = next(
        (r for r in idx if r["sessionId"] == session_id and r.get("ownerUid") == uid), None
    )
    now = now_iso()
    if existing:
        if title and title.strip():
            existing["title"] = title.strip()
        existing["updatedAt"] = now
        save_index(root, uid, idx)
        existing.setdefault("lastMessage", None)
        return ChatMeta(
            id=existing["id"],
            sessionId=existing["sessionId"],
            title=existing["title"],
            lastMessage=existing.get("lastMessage"),
            createdAt=existing["createdAt"],
            updatedAt=existing["updatedAt"],
        )

    next_id = (max((r["id"] for r in idx), default=0) + 1) if idx else 1
    row = {
        "id": next_id,
        "sessionId": session_id,
        "title": title.strip() or "New Chat",
        "lastMessage": None,
        "createdAt": now,
        "updatedAt": now,
        "ownerUid": uid,
        "ownerEmail": email,
    }
    idx.append(row)
    save_index(root, uid, idx)
    _save_chat(
        root,
        uid,
        session_id,
        {"sessionId": session_id, "messages": [], "seq": 0, "summary": "", "ownerUid": uid},
    )
    return ChatMeta(
        id=row["id"],
        sessionId=row["sessionId"],
        title=row["title"],
        lastMessage=row.get("lastMessage"),
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


def update_last(
    root: Path, uid: str, session_id: str, last_message: str | None, maybe_title: str | None
) -> ChatMeta:
    idx = load_index(root, uid)
    row = next((r for r in idx if r["sessionId"] == session_id and r.get("ownerUid") == uid), None)
    if not row:
        raise ValueError(f"Unknown sessionId: {session_id}")
    if last_message is not None:
        row["lastMessage"] = last_message
    if maybe_title and maybe_title.strip():
        row["title"] = maybe_title.strip()
    row["updatedAt"] = now_iso()
    save_index(root, uid, idx)
    row.setdefault("lastMessage", None)
    return ChatMeta(
        id=row["id"],
        sessionId=row["sessionId"],
        title=row["title"],
        lastMessage=row.get("lastMessage"),
        createdAt=row["createdAt"],
        updatedAt=row["updatedAt"],
    )


def append_message(
    root: Path,
    uid: str,
    session_id: str,
    role: str,
    content: str,
    attachments: list[Any] | None = None,
) -> ChatMessageRow:
    data = _load_chat(root, uid, session_id)
    seq = int(data.get("seq", 0)) + 1
    msg = {
        "id": seq,
        "sessionId": session_id,
        "role": role,
        "content": content,
        "createdAt": now_iso(),
    }
    norm_atts = _normalize_attachments(attachments)
    if norm_atts:
        msg["attachments"] = norm_atts
    data["messages"].append(msg)
    data["seq"] = seq
    _save_chat(root, uid, session_id, data)
    refresh_index_after_change(root, uid, session_id, data["messages"])
    return ChatMessageRow(
        id=seq,
        sessionId=session_id,
        role=role,
        content=content,
        createdAt=msg["createdAt"],
        attachments=norm_atts,
    )


def delete_message(root: Path, uid: str, session_id: str, message_id: int) -> int:
    data = _load_chat(root, uid, session_id)
    msgs = data.get("messages", [])
    before = len(msgs)
    msgs = [m for m in msgs if int(m.get("id", -1)) != int(message_id)]
    if len(msgs) == before:
        return 0
    data["messages"] = msgs
    _save_chat(root, uid, session_id, data)
    refresh_index_after_change(root, uid, session_id, msgs)
    return 1


def delete_messages_batch(
    root: Path, uid: str, session_id: str, message_ids: list[int]
) -> list[int]:
    wanted = {int(i) for i in (message_ids or [])}
    if not wanted:
        return []
    data = _load_chat(root, uid, session_id)
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
    _save_chat(root, uid, session_id, data)
    refresh_index_after_change(root, uid, session_id, keep)
    return deleted


def list_messages(root: Path, uid: str, session_id: str) -> list[ChatMessageRow]:
    data = _load_chat(root, uid, session_id)
    rows: list[ChatMessageRow] = []
    for m in data.get("messages", []):
        rows.append(
            ChatMessageRow(
                id=m["id"],
                sessionId=m["sessionId"],
                role=m["role"],
                content=m["content"],
                createdAt=m.get("createdAt"),
                attachments=m.get("attachments", []),
            )
        )
    return rows


def list_paged(
    root: Path, uid: str, page: int, size: int, ceiling_iso: str | None
) -> tuple[list[ChatMeta], int, int, bool]:
    rows = load_index(root, uid)
    rows = [r for r in rows if r.get("ownerUid") == uid]
    rows.sort(key=lambda r: r["updatedAt"], reverse=True)
    if ceiling_iso:
        rows = [r for r in rows if r["updatedAt"] <= ceiling_iso]

    total = len(rows)
    min_size = int(SETTINGS["chat_page_min_size"])
    max_size = int(SETTINGS["chat_page_max_size"])
    size = max(min_size, min(max_size, int(size)))
    page = max(0, int(page))

    start = page * size
    end = start + size
    page_rows = rows[start:end]
    total_pages = (total + size - 1) // size if total else 1
    last_flag = end >= total

    metas: list[ChatMeta] = []
    for r in page_rows:
        r.setdefault("lastMessage", None)
        metas.append(
            ChatMeta(
                id=r["id"],
                sessionId=r["sessionId"],
                title=r["title"],
                lastMessage=r.get("lastMessage"),
                createdAt=r["createdAt"],
                updatedAt=r["updatedAt"],
            )
        )
    return metas, total, total_pages, last_flag


def delete_batch(root: Path, uid: str, session_ids: list[str]) -> list[str]:
    for sid in session_ids:
        try:
            chat_path(root, sid).unlink(missing_ok=True)
        except Exception:
            pass
    for sid in session_ids:
        try:
            rag_delete_namespace(sid)
        except Exception:
            pass
    idx = load_index(root, uid)
    keep = [r for r in idx if not (r["sessionId"] in set(session_ids) and r.get("ownerUid") == uid)]
    save_index(root, uid, keep)
    return session_ids


def _save_chat(root: Path, uid: str, session_id: str, data: dict[str, Any]):
    atomic_write_encrypted(uid, root, chat_path(root, session_id), data)


def set_summary(root: Path, uid: str, session_id: str, new_summary: str) -> None:
    data = _load_chat(root, uid, session_id)
    data["summary"] = new_summary or ""
    _save_chat(root, uid, session_id, data)


def get_summary(root: Path, uid: str, session_id: str) -> str:
    data = _load_chat(root, uid, session_id)
    return str(data.get("summary") or "")


def edit_message(
    root: Path, uid: str, session_id: str, message_id: int, new_content: str
) -> ChatMessageRow | None:
    data = _load_chat(root, uid, session_id)
    msgs = data.get("messages", [])
    updated = None
    for m in msgs:
        if int(m.get("id", -1)) == int(message_id):
            m["content"] = new_content
            m["updatedAt"] = now_iso()
            if "attachments" in m and m["attachments"] is not None:
                m["attachments"] = _normalize_attachments(m["attachments"])
            updated = m
            break
    if not updated:
        return None
    _save_chat(root, uid, session_id, data)
    refresh_index_after_change(root, uid, session_id, msgs)
    return ChatMessageRow(
        id=updated["id"],
        sessionId=updated["sessionId"],
        role=updated["role"],
        content=updated["content"],
        createdAt=updated.get("createdAt"),
        attachments=updated.get("attachments", []),
    )


__all__ = [
    "ChatMessageRow",
    "_load_chat",
    "_save_chat",
    "append_message",
    "delete_batch",
    "delete_message",
    "delete_messages_batch",
    "edit_message",
    "get_summary",
    "list_messages",
    "list_paged",
    "set_summary",
    "update_last",
    "upsert_on_first_message",
]
