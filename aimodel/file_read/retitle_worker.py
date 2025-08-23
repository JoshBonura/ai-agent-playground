# aimodel/file_read/retitle_worker.py
from __future__ import annotations
import asyncio, logging
from .model_runtime import get_llm
from .store.index import load_index, save_index
from .store.base import now_iso

# Shared queue (session_id, messages)
queue: asyncio.Queue[tuple[str, list[dict]]] = asyncio.Queue()


async def start_worker():
    """Background loop to process retitle jobs one by one."""
    while True:
        session_id, messages = await queue.get()
        try:
            await _do_retitle(session_id, messages)
        except Exception as e:
            logging.exception("Retitle worker failed")
        finally:
            queue.task_done()


async def _do_retitle(session_id: str, messages: list[dict]):
    # Find first user message text
    first_user = next((m.get("content") for m in messages if m.get("role") == "user"), "")
    if not first_user:
        return

    llm = get_llm()
    out = llm.create_completion(
        prompt=f"Summarize this in 3–5 words: {first_user}",
        max_tokens=16,
        temperature=0.3,
    )
    title = out["choices"][0]["text"].strip()

    if title:
        idx = load_index()
        row = next((r for r in idx if r["sessionId"] == session_id), None)
        if row:
            row["title"] = title
            row["updatedAt"] = now_iso()
            save_index(idx)


def enqueue(session_id: str, messages: list[dict]):
    """Non-blocking add to queue."""
    if not messages:
        return
    try:
        queue.put_nowait((session_id, messages))
    except Exception as e:
        logging.warning(f"Failed to enqueue retitle: {e}")
