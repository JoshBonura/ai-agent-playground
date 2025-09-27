from __future__ import annotations
import asyncio
from collections import defaultdict
from threading import Event

from ..core.logging import get_logger
from ..core.settings import SETTINGS

log = get_logger(__name__)

eff = SETTINGS.effective()
GEN_SEMAPHORE = asyncio.Semaphore(int(eff["gen_semaphore_permits"]))
_ACTIVE: dict[str, int] = {}
_CANCELS: dict[str, Event] = {}

# NEW: track the server-side tasks currently streaming per session
_TASKS: dict[str, set[asyncio.Task]] = defaultdict(set)

def is_active(session_id: str) -> bool:
    return bool(_ACTIVE.get(session_id))

def mark_active(session_id: str, delta: int):
    _ACTIVE[session_id] = max(0, int(_ACTIVE.get(session_id, 0)) + delta)
    if _ACTIVE[session_id] == 0:
        _ACTIVE.pop(session_id, None)

def cancel_event(session_id: str) -> Event:
    ev = _CANCELS.get(session_id)
    if ev is None:
        ev = Event()
        _CANCELS[session_id] = ev
    return ev

# ---------- NEW helpers for hard-kill ----------
def register_task(session_id: str, task: asyncio.Task) -> None:
    _TASKS[session_id].add(task)

def unregister_task(session_id: str, task: asyncio.Task) -> None:
    s = _TASKS.get(session_id)
    if not s:
        return
    s.discard(task)
    if not s:
        _TASKS.pop(session_id, None)

async def cancel_tasks_for(session_id: str) -> int:
    """Cancel all running tasks for a session. Returns #tasks cancelled."""
    tasks = list(_TASKS.get(session_id, ()))
    for t in tasks:
        t.cancel()
    # yield to the loop so cancellations propagate
    if tasks:
        await asyncio.sleep(0)
    return len(tasks)

def cancel_all_sessions() -> int:
    """(Optional) global kill switch."""
    for ev in _CANCELS.values():
        ev.set()
    n = 0
    for sid, tasks in list(_TASKS.items()):
        for t in list(tasks):
            t.cancel()
            n += 1
        _TASKS.pop(sid, None)
    return n
