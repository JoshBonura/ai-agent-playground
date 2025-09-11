from __future__ import annotations

import asyncio
from threading import Event

from ..core.logging import get_logger
from ..core.settings import SETTINGS

log = get_logger(__name__)

eff = SETTINGS.effective()
GEN_SEMAPHORE = asyncio.Semaphore(int(eff["gen_semaphore_permits"]))
_ACTIVE: dict[str, int] = {}
_CANCELS: dict[str, Event] = {}


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
