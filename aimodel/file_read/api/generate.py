from __future__ import annotations

import asyncio
import json
import time
from threading import Event
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Body, Request
from fastapi.responses import StreamingResponse

from ..core.memory import build_system, get_session, pack_messages, roll_summary_if_needed
from ..model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody
from ..utils.streaming import (
    RUNJSON_START, RUNJSON_END, STOP_STRINGS,
    safe_token_count_messages, build_run_json, watch_disconnect,
)

router = APIRouter()

# ---- active-session tracking -------------------------------------------------
_ACTIVE: Dict[str, int] = {}

def is_active(session_id: str) -> bool:
    return bool(_ACTIVE.get(session_id))

def _mark_active(session_id: str, delta: int):
    _ACTIVE[session_id] = max(0, int(_ACTIVE.get(session_id, 0)) + delta)
    if _ACTIVE[session_id] == 0:
        _ACTIVE.pop(session_id, None)

# ---- concurrency + cancel ----------------------------------------------------
GEN_SEMAPHORE = asyncio.Semaphore(1)
_CANCELS: Dict[str, Event] = {}

def cancel_event(session_id: str) -> Event:
    ev = _CANCELS.get(session_id)
    if ev is None:
        ev = Event()
        _CANCELS[session_id] = ev
    return ev

@router.post("/cancel/{session_id}")
async def cancel_session(session_id: str):
    cancel_event(session_id).set()
    return {"ok": True}

# legacy alias kept
@router.post("/api/ai/cancel/{session_id}")
async def cancel_session_alias(session_id: str):
    return await cancel_session(session_id)

# ---- helpers -----------------------------------------------------------------
def _handle_incoming(session_id: str, incoming: List[Dict[str, str]]):
    st = get_session(session_id)
    for m in incoming:
        st["recent"].append(m)
    return st

# ---- main stream endpoint ----------------------------------------------------
@router.post("/generate/stream")
async def generate_stream(data: ChatBody = Body(...), request: Request = None):
    ensure_ready()
    llm = get_llm()

    session_id = data.sessionId or "default"
    if not data.messages:
        return StreamingResponse(iter([b"No messages provided."]), media_type="text/plain")

    incoming = [{"role": m.role, "content": m.content} for m in data.messages]
    st = _handle_incoming(session_id, incoming)

    out_budget = data.max_tokens or 512
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

    # prompt token estimate (robust)
    try:
        input_tokens_est = safe_token_count_messages(llm, packed)
    except Exception:
        input_tokens_est = None

    stop_ev = cancel_event(session_id)
    stop_ev.clear()

    async def streamer() -> AsyncGenerator[bytes, None]:
        async with GEN_SEMAPHORE:
            _mark_active(session_id, +1)  # <-- mark stream active

            disconnect_task = asyncio.create_task(watch_disconnect(request, stop_ev))
            q: asyncio.Queue = asyncio.Queue(maxsize=64)
            SENTINEL = object()

            def produce():
                t_start = time.perf_counter()
                t_first: Optional[float] = None
                t_last: Optional[float] = None
                finish_reason: Optional[str] = None
                err_text: Optional[str] = None
                out_parts: List[str] = []

                try:
                    stream = llm.create_chat_completion(
                        messages=packed,
                        stream=True,
                        max_tokens=out_budget,
                        temperature=(data.temperature or 0.6),
                        top_p=(data.top_p or 0.9),
                        top_k=40,
                        repeat_penalty=1.25,
                        stop=STOP_STRINGS,
                    )
                    for chunk in stream:
                        if stop_ev.is_set():
                            break

                        # capture finish_reason if present
                        try:
                            fr = chunk["choices"][0].get("finish_reason")
                            if fr:
                                finish_reason = fr
                        except Exception:
                            pass

                        piece = chunk["choices"][0]["delta"].get("content", "")
                        if not piece:
                            continue

                        now = time.perf_counter()
                        if t_first is None:
                            t_first = now
                        t_last = now
                        out_parts.append(piece)

                        while not stop_ev.is_set():
                            try:
                                q.put_nowait(piece)
                                break
                            except asyncio.QueueFull:
                                time.sleep(0.005)

                except Exception as e:
                    err_text = str(e)
                    try:
                        q.put_nowait(f"[aimodel] error: {e}")
                    except Exception:
                        pass
                finally:
                    # clear KV cache
                    try:
                        llm.reset()
                    except Exception:
                        pass

                    # Emit RUNJSON before sentinel
                    try:
                        out_text = "".join(out_parts)
                        run_json = build_run_json(
                            request_cfg={
                                "temperature": data.temperature or 0.6,
                                "top_p": data.top_p or 0.9,
                                "max_tokens": out_budget,
                            },
                            out_text=out_text,
                            t_start=t_start,
                            t_first=t_first,
                            t_last=t_last,
                            stop_set=stop_ev.is_set(),
                            finish_reason=finish_reason,
                            input_tokens_est=input_tokens_est,
                        )
                        q.put_nowait(RUNJSON_START + json.dumps(run_json) + RUNJSON_END)
                    except Exception:
                        pass

                    try:
                        q.put_nowait(SENTINEL)
                    except Exception:
                        pass

            producer = asyncio.create_task(asyncio.to_thread(produce))

            try:
                while True:
                    item = await q.get()
                    if item is SENTINEL:
                        break
                    if stop_ev.is_set():
                        break
                    yield (item if isinstance(item, bytes) else item.encode("utf-8"))
                if stop_ev.is_set():
                    yield b"\n\u23F9 stopped\n"
            finally:
                stop_ev.set()
                disconnect_task.cancel()
                try:
                    await asyncio.wait_for(producer, timeout=2.0)
                except Exception:
                    pass

                # Apply any pending queued ops now that this stream settled
                try:
                    from ..store import apply_pending_for
                    apply_pending_for(session_id)
                except Exception:
                    pass
                finally:
                    _mark_active(session_id, -1)  # <-- mark stream inactive

    return StreamingResponse(
        streamer(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

# alias path kept
@router.post("/api/ai/generate/stream")
async def generate_stream_alias(data: ChatBody = Body(...), request: Request = None):
    return await generate_stream(data, request)
