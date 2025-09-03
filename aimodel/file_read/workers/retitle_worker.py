# aimodel/file_read/retitle_worker.py
from __future__ import annotations
import asyncio, logging, re
from typing import Dict, List, Optional, Tuple

from ..runtime.model_runtime import get_llm
from ..store.index import load_index, save_index
from ..store.base import now_iso
from ..services.cancel import is_active, GEN_SEMAPHORE
from ..store.chats import _load_chat
from ..core.settings import SETTINGS

def S(key: str):
    return SETTINGS[key]

_PENDING: Dict[str, dict] = {}
_ENQUEUED: set[str] = set()
_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=int(S("retitle_queue_maxsize")))
_lock = asyncio.Lock()

def _preview(s: str) -> str:
    n = int(S("retitle_preview_chars"))
    ell = S("retitle_preview_ellipsis")
    s = (s or "")
    return (s[:n] + ell) if len(s) > n else s

def _is_substantial(text: str) -> bool:
    t = (text or "").strip()
    min_chars = int(S("retitle_min_substantial_chars"))
    require_alpha = bool(S("retitle_require_alpha"))
    if len(t) < min_chars:
        return False
    return (re.search(r"[A-Za-z]", t) is not None) if require_alpha else True

def _pick_source(messages: List[dict]) -> Optional[str]:
    if not messages:
        print("[retitle] no messages to pick from")
        return None

    min_user_len = int(S("retitle_min_user_chars"))
    print(f"[retitle] min_user_len={min_user_len}, total_msgs={len(messages)}")

    # 1. Prefer last substantial user message
    for m in reversed(messages):
        if m.get("role") == "user":
            txt = (m.get("content") or "").strip()
            print(f"[retitle] check user msg len={len(txt)} preview={txt[:40]!r}")
            if len(txt) >= min_user_len and _is_substantial(txt):
                print("[retitle] PICK user message")
                return txt

    # 2. Fallback to last substantial assistant message
    for m in reversed(messages):
        if m.get("role") == "assistant":
            txt = (m.get("content") or "").strip()
            print(f"[retitle] check assistant msg len={len(txt)} preview={txt[:40]!r}")
            if _is_substantial(txt):
                print("[retitle] PICK assistant message")
                return txt

    print("[retitle] no suitable message found")
    return None

def _sanitize_title(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"(?i)^(?:how\s+to|steps?\s+to|guide\s+to|tutorial:\s*|to)\s+", "", s).strip()
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
    s = re.sub(r"[.:;,\-\s]+$", "", s)
    s = re.sub(r"(?i)^(?:a|an|the)\s+", "", s).strip()
    max_words = int(S("retitle_sanitize_max_words"))
    max_chars = int(S("retitle_sanitize_max_chars"))
    if max_words > 0:
        words = s.split()
        s = " ".join(words[:max_words])
    if max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip()
    return s

def _make_title(llm, src: str) -> str:
    sys = S("retitle_llm_sys_inst")
    hard = ("You generate a concise chat title.\n"
            "Return ONLY a short noun phrase (no verbs, no 'how to', no 'to ...'). "
            "No trailing punctuation. Max 6 words.")
    sys = f"{hard}\n\n{sys}" if sys else hard

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
    raw = re.sub(r"(?i)^(?:how\s+to|to)\s+", "", raw).strip()
    raw = re.sub(r"^`{1,3}|`{1,3}$", "", raw).strip()
    raw = re.sub(r"[.:;,\-\s]+$", "", raw)
    return raw

async def start_worker():
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
    if not bool(S("retitle_enable")):
        return
    await asyncio.sleep(int(S("retitle_grace_ms")) / 1000.0)
    waited = 0
    backoff = int(S("retitle_active_backoff_start_ms"))
    backoff_max = int(S("retitle_active_backoff_max_ms"))
    backoff_total = int(S("retitle_active_backoff_total_ms"))
    growth = float(S("retitle_active_backoff_growth"))
    while is_active(session_id) and waited < backoff_total:
        await asyncio.sleep(backoff / 1000.0)
        waited += backoff
        backoff = min(int(backoff * growth), backoff_max)
    async with _lock:
        snapshot = _PENDING.pop(session_id, None)
        _ENQUEUED.discard(session_id)
    if not snapshot:
        return
    messages, job_seq = _extract_job(snapshot)
    try:
        cur_seq = int((_load_chat(session_id) or {}).get("seq") or 0)
    except Exception:
        cur_seq = job_seq
    if cur_seq > job_seq:
        print(f"[retitle] SKIP (stale) session={session_id} job_seq={job_seq} current_seq={cur_seq}")
        return
    src = _pick_source(messages) or ""
    if not src.strip():
        return
    print(f"[retitle] START session={session_id} job_seq={job_seq} src={_preview(src)!r}")
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
    if bool(S("retitle_enable_sanitize")):
        title = _sanitize_title(title_raw)
    else:
        title = title_raw
    print(f"[retitle] FINISH session={session_id} -> {title!r}")
    if not title:
        return
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
    if not session_id:
        return
    if not isinstance(messages, list):
        messages = []
    if job_seq is None:
        try:
            job_seq = max(int(m.get("id") or 0) for m in messages) if messages else 0
        except Exception:
            job_seq = 0
    snap = {"messages": messages, "job_seq": int(job_seq)}
    async def _put():
        async with _lock:
            _PENDING[session_id] = snap
            if session_id not in _ENQUEUED:
                _ENQUEUED.add(session_id)
                try:
                    _queue.put_nowait(session_id)
                except Exception as e:
                    logging.warning(f"Failed to enqueue retitle: {e}")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_put())
    except RuntimeError:
        asyncio.run(_put())
