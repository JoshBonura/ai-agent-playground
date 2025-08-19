from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from .base import INDEX_PATH, atomic_write, ensure_dirs, now_iso

def load_index() -> List[Dict]:
    ensure_dirs()
    try:
        with INDEX_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_index(rows: List[Dict]):
    atomic_write(INDEX_PATH, rows)

@dataclass
class ChatMeta:
    id: int
    sessionId: str
    title: str
    lastMessage: Optional[str]
    createdAt: str
    updatedAt: str

def refresh_index_after_change(session_id: str, messages: List[Dict]) -> None:
    idx = load_index()
    row = next((r for r in idx if r["sessionId"] == session_id), None)
    if not row:
        return
    row["updatedAt"] = now_iso()
    last_asst = None
    for m in reversed(messages):
        if m.get("role") == "assistant":
            last_asst = m.get("content") or None
            break
    row["lastMessage"] = last_asst
    save_index(idx)
