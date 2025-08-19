from __future__ import annotations
import json
from typing import Callable, Dict, List
from .base import PENDING_PATH, OLD_PENDING_DELETES, atomic_write, _lock  # <-- import _lock
from .chats import _load_chat, _save_chat
from .index import refresh_index_after_change


def _load_pending() -> Dict[str, List[Dict[str, object]]]:
    try:
        with PENDING_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def _save_pending(d: Dict[str, List[Dict[str, object]]]):
    atomic_write(PENDING_PATH, d)

def _migrate_old_pending_if_any():
    try:
        if OLD_PENDING_DELETES.exists():
            legacy = json.loads(OLD_PENDING_DELETES.read_text("utf-8"))
            if isinstance(legacy, dict):
                with _lock:
                    cur = _load_pending()
                    for sid, arr in legacy.items():
                        lst = cur.setdefault(sid, [])
                        for req in arr or []:
                            lst.append({
                                "type": "deleteMessages",
                                "payload": {
                                    "messageIds": [int(i) for i in (req.get("messageIds") or [])],
                                    "tailAssistant": bool(req.get("tailAssistant") or False),
                                },
                            })
                    _save_pending(cur)
            OLD_PENDING_DELETES.unlink(missing_ok=True)
    except Exception:
        pass

def enqueue_pending(session_id: str, op_type: str, payload: Dict[str, object]):
    _migrate_old_pending_if_any()
    with _lock:
        pend = _load_pending()
        q = pend.setdefault(session_id, [])
        q.append({"type": op_type, "payload": payload or {}})
        _save_pending(pend)

def _consume_queue(session_id: str) -> List[Dict[str, object]]:
    with _lock:
        pend = _load_pending()
        arr = pend.pop(session_id, [])
        _save_pending(pend)
        return arr

def list_pending_sessions() -> List[str]:
    _migrate_old_pending_if_any()
    with _lock:
        return list(_load_pending().keys())
    
    

# ... (rest unchanged) ...


# --- op handlers ---


def _op_delete_messages(session_id: str, payload: Dict[str, object]) -> List[int]:
    ids = set(int(i) for i in (payload.get("messageIds") or []))
    tail_assistant = bool(payload.get("tailAssistant") or False)

    data = _load_chat(session_id)
    msgs = data.get("messages", [])
    if not isinstance(msgs, list):
        msgs = []

    found_tail = False
    if tail_assistant:
        # try to include the most recent assistant message
        for m in reversed(msgs):
            if m.get("role") == "assistant":
                try:
                    ids.add(int(m.get("id")))
                    found_tail = True
                except Exception:
                    pass
                break

    # If we intended to delete the tail assistant but it hasn't been persisted yet,
    # DEFER instead of dropping the op. `apply_pending_for` will catch this and requeue.
    if not ids and tail_assistant and not found_tail:
        raise RuntimeError("defer_tail_assistant")

    if not ids:
        return []

    keep, deleted = [], []
    for m in msgs:
        mid = int(m.get("id", -1))
        if mid in ids:
            deleted.append(mid)
        else:
            keep.append(m)

    if deleted:
        data["messages"] = keep
        _save_chat(session_id, data)
        refresh_index_after_change(session_id, keep)
    return deleted

def _apply_op(session_id: str, op: Dict[str, object]) -> Dict[str, object]:
    t = str(op.get("type") or "")
    payload = op.get("payload") or {}
    if t == "deleteMessages":
        deleted = _op_delete_messages(session_id, payload)
        return {"type": t, "ok": True, "deleted": deleted}
    return {"type": t, "ok": False, "reason": "unknown_op"}

def apply_pending_for(session_id: str) -> List[Dict[str, object]]:
    ops = _consume_queue(session_id)
    results: List[Dict[str, object]] = []
    for op in ops:
        try:
            results.append(_apply_op(session_id, op))
        except Exception as e:
    # Requeue on failure (front)
            pend = _load_pending()
            pend.setdefault(session_id, []).insert(0, op)
            _save_pending(pend)
            results.append({"type": op.get("type"), "ok": False, "error": str(e)})
    return results

def process_all_pending(is_active: Callable[[str], bool]) -> Dict[str, List[Dict[str, object]]]:
    out: Dict[str, List[Dict[str, object]]] = {}
    _migrate_old_pending_if_any()
    sessions = list(_load_pending().keys())
    for sid in sessions:
        try:
            if is_active(sid):
                continue
            res = apply_pending_for(sid)
            if res:
                out[sid] = res
        except Exception:
            pass
    return out
