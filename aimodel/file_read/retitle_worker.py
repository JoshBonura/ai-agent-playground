# aimodel/file_read/retitle_worker.py
from __future__ import annotations
import asyncio, logging, re
from typing import Dict, List, Optional, Tuple

from .model_runtime import get_llm
from .store.index import load_index, save_index
from .store.base import now_iso
from .services.cancel import is_active, GEN_SEMAPHORE  # serialize with main generation
from .store.chats import _load_chat  # for current seq watermark

# -----------------------------------------------------------------------------
# Coalesced per-session queue (last-write-wins)
# -----------------------------------------------------------------------------
# We store only the latest snapshot + watermark per session. The worker consumes
# session IDs; when it handles a session, it reads the latest snapshot once.
_PENDING: Dict[str, dict] = {}
_ENQUEUED: set[str] = set()
_queue: asyncio.Queue[str] = asyncio.Queue()
_lock = asyncio.Lock()  # guards _PENDING/_ENQUEUED

# ---- Timings (intervals) -----------------------------------------------------
_GRACE_MS = 1000  # debounce after stream (was 500)
_ACTIVE_BACKOFF_START_MS = 75     # initial wait while session is active (was fixed 100ms)
_ACTIVE_BACKOFF_MAX_MS = 600      # cap per-iteration sleep
_ACTIVE_BACKOFF_TOTAL_MS = 20000  # max total wait while active (~20s)

def _preview(s: str, n: int = 60) -> str:
    s = s or ""
    return (s[:n] + "…") if len(s) > n else s

def _is_substantial(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= 12 and re.search(r"[A-Za-z]", t) is not None

def _pick_source(messages: List[dict]) -> Optional[str]:
    """Choose best text to title: first substantial user message; fallback to latest substantial user."""
    if not messages:
        return None
    # first substantial user
    for m in messages:
        if (m.get("role") == "user") and _is_substantial(m.get("content", "")):
            return m.get("content", "")
    # fallback: latest substantial user
    for m in reversed(messages):
        if (m.get("role") == "user") and _is_substantial(m.get("content", "")):
            return m.get("content", "")
    # final fallback: first user at all
    for m in messages:
        if m.get("role") == "user":
            return m.get("content", "")
    return None

def _sanitize_title(s: str) -> str:
    """Single line, 3–5 words, no quotes/numbering/punct clutter."""
    if not s:
        return ""
    s = s.strip()
    # drop common prefixes like "Expanded explanation:", bullets, quotes
    s = re.sub(r'^\s*("[^"]*"|\'[^\']*\'|[-*•]+|\d+\.)\s*', "", s)
    s = s.strip().strip('"\'').strip()
    # keep letters, digits, spaces; collapse spaces
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # limit to 5 words / ~40 chars
    words = s.split()
    s = " ".join(words[:5])
    if len(s) > 40:
        s = s[:40].rstrip()
    return s

def _make_title(llm, src: str) -> str:
    sys = (
        "You generate ultra-concise chat titles.\n"
        "Rules: 2–5 words, Title Case, nouns/adjectives only.\n"
        "No articles (a, an, the). No verbs. No punctuation. One line.\n"
        "Output only the title."
    )

    examples = [
        {"role": "user", "content": "police station"},
        {"role": "assistant", "content": "Police Station"},
        {"role": "user", "content": "fire truck"},
        {"role": "assistant", "content": "Fire Truck"},
        {"role": "user", "content": "how do i install node on windows"},
        {"role": "assistant", "content": "Node Installation Windows"},
    ]

    out = llm.create_chat_completion(
        messages=[{"role": "system", "content": sys}, *examples, {"role": "user", "content": src}],
        max_tokens=12,
        temperature=0.1,
        top_p=1.0,
        stream=False,
        stop=["\n", "."],  # cut off if it tries to continue a sentence
    )
    # trust the model to format; just trim whitespace/quotes
    raw = (out["choices"][0]["message"]["content"] or "").strip().strip('"').strip("'")
    return raw

async def start_worker():
    """Background loop to process retitle jobs one by one."""
    while True:
        sid = await _queue.get()
        try:
            await _process_session(sid)
        except Exception:
            logging.exception("Retitle worker failed")
        finally:
            _queue.task_done()

def _extract_job(snapshot: dict) -> Tuple[List[dict], int]:
    msgs = snapshot.get("messages") or []
    job_seq = int(snapshot.get("job_seq") or 0)
    return msgs, job_seq

async def _process_session(session_id: str):
    # allow quick follow-up enqueues to coalesce
    await asyncio.sleep(_GRACE_MS / 1000.0)

    # lower priority than generation: wait while this session is active
    waited = 0
    backoff = _ACTIVE_BACKOFF_START_MS
    while is_active(session_id) and waited < _ACTIVE_BACKOFF_TOTAL_MS:
        await asyncio.sleep(backoff / 1000.0)
        waited += backoff
        # exponential backoff with cap
        backoff = min(int(backoff * 1.5), _ACTIVE_BACKOFF_MAX_MS)

    # fetch latest coalesced snapshot
    async with _lock:
        snapshot = _PENDING.pop(session_id, None)
        _ENQUEUED.discard(session_id)

    if not snapshot:
        return

    messages, job_seq = _extract_job(snapshot)

    # stale guard: if chat seq has advanced, skip (a newer enqueue will run)
    try:
        cur_seq = int((_load_chat(session_id) or {}).get("seq") or 0)
    except Exception:
        cur_seq = job_seq
    if cur_seq > job_seq:
        print(f"[retitle] SKIP (stale) session={session_id} job_seq={job_seq} current_seq={cur_seq}")
        return

    # pick source text
    src = _pick_source(messages) or ""
    if not src.strip():
        return

    print(f"[retitle] START session={session_id} job_seq={job_seq} src={_preview(src)!r}")

    # Serialize with main generation semaphore; run LLM call in a worker thread
    async with GEN_SEMAPHORE:
        llm = get_llm()
        try:
            title = await asyncio.to_thread(_make_title, llm, src)
        except Exception as e:
            logging.exception("retitle: LLM error: %s", e)
            return
        finally:
            try:
                llm.reset()
            except Exception:
                pass

    print(f"[retitle] FINISH session={session_id} -> {title!r}")

    if not title:
        return

    # write only if changed
    idx = load_index()
    row = next((r for r in idx if r.get("sessionId") == session_id), None)
    if not row:
        return
    if (row.get("title") or "").strip() == title:
        return

    row["title"] = title
    row["updatedAt"] = now_iso()
    save_index(idx)

def enqueue(session_id: str, messages: List[dict], *, job_seq: Optional[int] = None):
    """Coalesced enqueue; last-write-wins per session, with a seq watermark."""
    if not session_id:
        return
    if not isinstance(messages, list):
        messages = []
    # infer watermark if not provided (max message id)
    if job_seq is None:
        try:
            job_seq = max(int(m.get("id") or 0) for m in messages) if messages else 0
        except Exception:
            job_seq = 0

    snap = {"messages": messages, "job_seq": int(job_seq)}

    async def _put():
        async with _lock:
            _PENDING[session_id] = snap  # overwrite older snapshot
            if session_id not in _ENQUEUED:
                _ENQUEUED.add(session_id)
                try:
                    _queue.put_nowait(session_id)
                except Exception as e:
                    logging.warning(f"Failed to enqueue retitle: {e}")

    # enqueue can be called from sync contexts; schedule safely
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_put())
    except RuntimeError:
        # no running loop (unlikely here); fall back to a temp loop
        asyncio.run(_put())
