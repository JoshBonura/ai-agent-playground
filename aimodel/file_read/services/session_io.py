from __future__ import annotations

from ..core.logging import get_logger
from ..core.packing_memory_core import get_session
from ..store import set_summary as store_set_summary

log = get_logger(__name__)


def handle_incoming(session_id: str, incoming: list[dict[str, str]]):
    st = get_session(session_id)
    st.setdefault("_ephemeral_web", [])
    for m in incoming:
        st["recent"].append(m)
    return st


def persist_summary(session_id: str, summary: str):
    try:
        store_set_summary(session_id, summary)
    except Exception:
        pass
