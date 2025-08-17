from __future__ import annotations

import asyncio
from typing import Dict, List, AsyncGenerator
from threading import Event

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from .model import llm
from .schemas import ChatBody
from .memory import (
    get_session,
    pack_messages,
    roll_summary_if_needed,
    build_system,
)

app = FastAPI()

@app.get("/health")
async def health():
    return {"ok": True}

def handle_incoming(session_id: str, incoming: List[Dict[str, str]]):
    st = get_session(session_id)
    for m in incoming:
        st["recent"].append(m)
    return st

# ---- cancellation + concurrency ----
GEN_SEMAPHORE = asyncio.Semaphore(1)
_CANCELS: dict[str, Event] = {}

def cancel_event(session_id: str) -> Event:
    ev = _CANCELS.get(session_id)
    if ev is None:
        ev = Event()
        _CANCELS[session_id] = ev
    return ev

@app.post("/cancel/{session_id}")
async def cancel_session(session_id: str):
    cancel_event(session_id).set()
    return {"ok": True}

@app.post("/generate/stream")
async def generate_stream(data: ChatBody, request: Request):
    session_id = data.sessionId or "default"
    if not data.messages:
        return StreamingResponse(iter([b"No messages provided."]), media_type="text/plain")

    incoming = [{"role": m.role, "content": m.content} for m in data.messages]
    st = handle_incoming(session_id, incoming)

    out_budget = data.max_tokens or 80
    system_text = build_system(style="", short=False, bullets=False)

    packed, input_budget = pack_messages(
        style="",
        short=False,
        bullets=False,
        summary=st["summary"],
        recent=st["recent"],
        max_ctx=4096,
        out_budget=out_budget,
    )
    packed, st["summary"] = roll_summary_if_needed(
        packed=packed,
        recent=st["recent"],
        summary=st["summary"],
        input_budget=input_budget,
        system_text=system_text,
    )

    stop_ev = cancel_event(session_id)
    stop_ev.clear()

    async def watch_disconnect():
        # client already gone?
        if await request.is_disconnected():
            stop_ev.set(); return
        while not stop_ev.is_set():
            await asyncio.sleep(0.2)
            if await request.is_disconnected():
                stop_ev.set(); break

    async def streamer() -> AsyncGenerator[bytes, None]:
        async with GEN_SEMAPHORE:
            disconnect_task = asyncio.create_task(watch_disconnect())

            q: asyncio.Queue = asyncio.Queue(maxsize=64)
            SENTINEL = object()

            def produce():
                """Run llama in a thread and respect stop_ev *between tokens*."""
                try:
                    stream = llm.create_chat_completion(
                        messages=packed,
                        stream=True,
                        max_tokens=out_budget,
                        temperature=(data.temperature or 0.6),
                        top_p=(data.top_p or 0.9),
                        top_k=40,
                        repeat_penalty=1.25,
                        stop=["</s>", "User:", "\nUser:"],
                    )
                    for chunk in stream:
                        if stop_ev.is_set():
                            break
                        piece = chunk["choices"][0]["delta"].get("content", "")
                        if not piece:
                            continue
                        # Non-blocking put with small backoff to keep latency tight
                        while not stop_ev.is_set():
                            try:
                                q.put_nowait(piece)
                                break
                            except asyncio.QueueFull:
                                import time; time.sleep(0.005)
                except Exception as e:
                    try: q.put_nowait(f"[aimodel] error: {e}")
                    except Exception: pass
                finally:
                    # Hard stop: clear KV cache so generation doesn't keep going
                    try: llm.reset()
                    except Exception: pass
                    try: q.put_nowait(SENTINEL)
                    except Exception: pass

            producer = asyncio.create_task(asyncio.to_thread(produce))

            try:
                while True:
                    item = await q.get()
                    if item is SENTINEL:
                        break
                    if stop_ev.is_set():
                        break
                    yield (item if isinstance(item, bytes) else item.encode("utf-8"))
                # optional visible tail so the client knows we stopped
                if stop_ev.is_set():
                    yield b"\n\u23F9 stopped\n"
            finally:
                stop_ev.set()
                disconnect_task.cancel()
                try:
                    await asyncio.wait_for(producer, timeout=2.0)
                except Exception:
                    pass

    return StreamingResponse(
        streamer(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
