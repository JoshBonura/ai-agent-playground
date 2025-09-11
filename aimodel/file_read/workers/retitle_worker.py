from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..runtime.model_runtime import get_llm
from ..services.cancel import GEN_SEMAPHORE, is_active
from ..store.base import now_iso
from ..store.chats import _load_chat
from ..store.index import load_index, save_index

log = get_logger(__name__)


def S(key: str):
    return SETTINGS[key]


# Key the queue by user+session to avoid collisions across users
def _key(uid: str, session_id: str) -> str:
    return f"{uid}:{session_id}"


# pending snapshot: { root, uid, session_id, messages, job_seq }
_PENDING: dict[str, dict[str, Any]] = {}
_ENQUEUED: set[str] = set()
_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=int(S("retitle_queue_maxsize")))
_lock = asyncio.Lock()


def _preview(s: str) -> str:
    n = int(S("retitle_preview_chars"))
    ell = S("retitle_preview_ellipsis")
    s = s or ""
    return (s[:n] + ell) if len(s) > n else s


def _is_substantial(text: str) -> bool:
    t = (text or "").strip()
    min_chars = int(S("retitle_min_substantial_chars"))
    require_alpha = bool(S("retitle_require_alpha"))
    if len(t) < min_chars:
        return False
    return (re.search(r"[A-Za-z]", t) is not None) if require_alpha else True


def _pick_source(messages: list[dict]) -> str | None:
    if not messages:
        return None
    min_user_len = int(S("retitle_min_user_chars"))
    for m in reversed(messages):
        if m.get("role") == "user":
            txt = (m.get("content") or "").strip()
            if len(txt) >= min_user_len and _is_substantial(txt):
                return txt
    for m in reversed(messages):
        if m.get("role") == "assistant":
            txt = (m.get("content") or "").strip()
            if _is_substantial(txt):
                return txt
    return None


def _sanitize_title(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    drop_prefix_re = S("retitle_sanitize_drop_prefix_regex")
    if drop_prefix_re:
        s = re.sub(drop_prefix_re, "", s)
    if bool(S("retitle_sanitize_strip_quotes")):
        s = s.strip().strip('"').strip("'").strip()
    replace_not_allowed_re = S("retitle_sanitize_replace_not_allowed_regex")
    replace_with = S("retitle_sanitize_replace_with")
    if replace_not_allowed_re:
        s = re.sub(replace_not_allowed_re, replace_with, s)
    s = re.sub(r"\s+", " ", s).strip()
    max_words = int(S("retitle_sanitize_max_words"))
    max_chars = int(S("retitle_sanitize_max_chars"))
    if max_words > 0:
        words = s.split()
        s = " ".join(words[:max_words])
    if max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip()
    return s


def _make_title(llm, src: str) -> str:
    hard = SETTINGS.get("retitle_llm_hard_prefix") or ""
    sys_extra = SETTINGS.get("retitle_llm_sys_inst") or ""
    sys = f"{hard}\n\n{sys_extra}".strip()
    user_text = f"{S('retitle_user_prefix')}{src}{S('retitle_user_suffix')}"
    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": user_text},
    ]
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=int(S("retitle_llm_max_tokens")),
        temperature=float(S("retitle_llm_temperature")),
        top_p=float(S("retitle_llm_top_p")),
        stream=False,
        stop=S("retitle_llm_stop"),
    )
    raw = (out["choices"][0]["message"]["content"] or "").strip().strip('"').strip("'")
    strip_regex = SETTINGS.get("retitle_strip_regex")
    if strip_regex:
        raw = re.sub(strip_regex, "", raw).strip()
    raw = re.sub(r"^`{1,3}|`{1,3}$", "", raw).strip()
    raw = re.sub(r"[.:;,\-\s]+$", "", raw)
    return raw


async def start_worker():
    while True:
        key = await _queue.get()
        try:
            await _process_session(key)
        except Exception:
            logging.exception("Retitle worker failed")
        finally:
            _queue.task_done()


def _extract_job(snapshot: dict) -> tuple[list[dict], int]:
    msgs = snapshot.get("messages") or []
    job_seq = int(snapshot.get("job_seq") or 0)
    return msgs, job_seq


async def _process_session(key: str):
    if not bool(S("retitle_enable")):
        return

    # small grace to avoid racing while generation is still streaming
    await asyncio.sleep(int(S("retitle_grace_ms")) / 1000.0)

    # backoff if the chat is still active
    waited = 0
    backoff = int(S("retitle_active_backoff_start_ms"))
    backoff_max = int(S("retitle_active_backoff_max_ms"))
    backoff_total = int(S("retitle_active_backoff_total_ms"))
    growth = float(S("retitle_active_backoff_growth"))
    # The is_active flag is keyed by session id; strip uid part
    _, session_id = key.split(":", 1)
    while is_active(session_id) and waited < backoff_total:
        await asyncio.sleep(backoff / 1000.0)
        waited += backoff
        backoff = min(int(backoff * growth), backoff_max)

    async with _lock:
        snapshot = _PENDING.pop(key, None)
        _ENQUEUED.discard(key)
    if not snapshot:
        return

    root: Path = snapshot["root"]
    uid: str = snapshot["uid"]
    session_id: str = snapshot["session_id"]
    messages, job_seq = _extract_job(snapshot)

    # Check current seq to avoid retitling after more messages arrived
    try:
        cur_seq = int((_load_chat(root, uid, session_id) or {}).get("seq") or 0)
    except Exception:
        cur_seq = job_seq
    if cur_seq > job_seq:
        return

    src = _pick_source(messages) or ""
    if not src.strip():
        return

    async with GEN_SEMAPHORE:
        llm = get_llm()
        try:
            title_raw = await asyncio.to_thread(_make_title, llm, src)
        except Exception as e:
            logging.exception("retitle: LLM error: %s", e)
            return
        finally:
            try:
                llm.reset()
            except Exception:
                pass

    title = _sanitize_title(title_raw) if bool(S("retitle_enable_sanitize")) else title_raw
    if not title:
        return

    # Update encrypted per-user index
    idx = load_index(root, uid)
    row = next(
        (r for r in idx if r.get("sessionId") == session_id and r.get("ownerUid") == uid), None
    )
    if not row:
        return
    if (row.get("title") or "").strip() == title:
        return

    row["title"] = title
    row["updatedAt"] = now_iso()
    save_index(root, uid, idx)


def enqueue(
    root: Path, uid: str, session_id: str, messages: list[dict], *, job_seq: int | None = None
):
    if not session_id or not uid:
        return
    if not isinstance(messages, list):
        messages = []
    if job_seq is None:
        try:
            job_seq = max(int(m.get("id") or 0) for m in messages) if messages else 0
        except Exception:
            job_seq = 0

    k = _key(uid, session_id)
    snap = {
        "root": root,
        "uid": uid,
        "session_id": session_id,
        "messages": messages,
        "job_seq": int(job_seq),
    }

    async def _put():
        async with _lock:
            _PENDING[k] = snap
            if k not in _ENQUEUED:
                _ENQUEUED.add(k)
                try:
                    _queue.put_nowait(k)
                except Exception as e:
                    logging.warning(f"Failed to enqueue retitle: {e}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_put())
    except RuntimeError:
        asyncio.run(_put())
