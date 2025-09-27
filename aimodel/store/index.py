from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.logging import get_logger
from .base import (atomic_write_encrypted, index_path, now_iso,
                   read_json_encrypted)

log = get_logger(__name__)


def load_index(root: Path, uid: str) -> list[dict]:
    p = index_path(root)
    if not p.exists():
        return []
    try:
        return read_json_encrypted(uid, root, p)
    except Exception as e:
        log.warning(f"[index] failed to read index at {p}: {e!r}")
        return []


def save_index(root: Path, uid: str, rows: list[dict]):
    atomic_write_encrypted(uid, root, index_path(root), rows)


@dataclass
class ChatMeta:
    id: int
    sessionId: str
    title: str
    lastMessage: str | None
    createdAt: str
    updatedAt: str


def refresh_index_after_change(root: Path, uid: str, session_id: str, messages: list[dict]) -> None:
    idx = load_index(root, uid)
    row = next((r for r in idx if r["sessionId"] == session_id and r.get("ownerUid") == uid), None)
    if not row:
        return
    row["updatedAt"] = now_iso()
    last_asst = None
    for m in reversed(messages or []):
        if m.get("role") == "assistant":
            last_asst = m.get("content") or None
            break
    row["lastMessage"] = last_asst
    save_index(root, uid, idx)
