# aimodel/file_read/services/generate_flow.py
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import asdict

from fastapi.responses import StreamingResponse

from ..deps.license_deps import is_request_pro_activated
from ..core.settings import SETTINGS
from ..utils.streaming import RUNJSON_END, RUNJSON_START
from ..core.logging import get_logger

from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .streaming_worker import run_stream as _run_stream
from .generate_pipeline import prepare_generation_with_telemetry

log = get_logger(__name__)
run_stream: Callable[..., AsyncIterator[bytes]] = _run_stream


# ---------- SSE helpers ----------

def _sse(event: str | None = None, data: str | dict | None = None, comment: str | None = None) -> bytes:
    """Build an SSE frame: comment (ignored by clients) or event+data."""
    if comment is not None:
        return f": {comment}\n\n".encode("utf-8")

    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")

    if data is None:
        lines.append("data:")
    else:
        if isinstance(data, (dict, list)):
            from json import dumps
            payload = dumps(data, ensure_ascii=False)
        else:
            payload = str(data)
        for line in payload.splitlines() or [""]:
            lines.append(f"data: {line}")

    return ("\n".join(lines) + "\n\n").encode("utf-8")


async def _wait_for_stop(ev: asyncio.Event) -> bool:
    while not ev.is_set():
        await asyncio.sleep(0.05)
    return True


# ---------- main ----------

async def generate_stream_flow(data, request) -> StreamingResponse:
    """
    - Open SSE immediately; send comment heartbeats during PREP.
    - Race STOP vs PREP so cancel works before first token.
    - Catch PREP errors so the stream doesn't close silently.
    """
    eff0 = SETTINGS.effective()
    stopped_marker = eff0.get("stopped_line_marker") or ""
    early_sid = getattr(data, "sessionId", None) or eff0["default_session_id"]

    # Log settings/flags early so we can compare main vs worker processes
    try:
        log.info(
            "[gen] startup flags sid=%s runjson_emit=%s stopped_line=%s pro=%s",
            early_sid,
            bool(SETTINGS.runjson_emit),
            bool(SETTINGS.stream_emit_stopped_line),
            bool(is_request_pro_activated()),
        )
    except Exception:
        pass

    stop_ev = cancel_event(early_sid)
    if stop_ev.is_set():
        log.info("[gen] clearing stale stop at start sid=%s ev_id=%s", early_sid, id(stop_ev))
        stop_ev.clear()

    async def streamer() -> AsyncGenerator[bytes, None]:
        nonlocal stop_ev

        # 1) Open/flush and send invisible comment
        yield _sse(comment="open")
        await asyncio.sleep(0)
        log.info("[gen] stream opened sid=%s ev_id=%s", early_sid, id(stop_ev))

        # 2) PREP vs STOP race with heartbeats
        log.info("[gen] PREP start sid=%s", early_sid)
        prep_task = asyncio.create_task(prepare_generation_with_telemetry(data, stop_ev=stop_ev))
        stop_task = asyncio.create_task(_wait_for_stop(stop_ev))

        prep: object | None = None
        try:
            while True:
                done, _ = await asyncio.wait(
                    {prep_task, stop_task},
                    timeout=0.5,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # keep pipe warm; ignored by proper SSE clients
                yield _sse(comment="hb")

                if stop_task in done:
                    log.info("[gen] STOP during PREP sid=%s ev_id=%s", early_sid, id(stop_ev))
                    try:
                        if not prep_task.done():
                            prep_task.cancel()
                            await asyncio.gather(prep_task, return_exceptions=True)
                        else:
                            _ = prep_task.exception()
                    except Exception:
                        pass
                    if SETTINGS.stream_emit_stopped_line:
                        yield _sse(data=stopped_marker)
                    return

                if prep_task in done:
                    try:
                        prep = prep_task.result()
                    except Exception as e:
                        log.exception("[gen] PREP failed sid=%s err=%s", early_sid, e)
                        # Optional: emit a small error event that the FE can log (but ignore in chat text)
                        yield _sse(event="phase", data={"state": "prep_error"})
                        # Show stopped marker if configured; otherwise just end
                        if SETTINGS.stream_emit_stopped_line:
                            yield _sse(data=stopped_marker)
                        return
                    break
        finally:
            try:
                if prep is None:
                    if not prep_task.done():
                        prep_task.cancel()
                        await asyncio.gather(prep_task, return_exceptions=True)
                    else:
                        _ = prep_task.exception()
            except Exception:
                pass

        # 3) If PREP changed session id, swap/correct stop_ev
        if getattr(prep, "session_id", early_sid) != early_sid:
            new_sid = prep.session_id  # type: ignore[attr-defined]
            stop_ev = cancel_event(new_sid)
            log.info("[gen] sid switch %s -> %s ev_id=%s set=%s",
                     early_sid, new_sid, id(stop_ev), stop_ev.is_set())
            if stop_ev.is_set():
                log.info("[gen] clearing stale stop after sid switch sid=%s", new_sid)
                stop_ev.clear()

        # paranoid early stop
        if stop_ev.is_set():
            log.info("[gen] STOP after PREP sid=%s", getattr(prep, "session_id", early_sid))
            if SETTINGS.stream_emit_stopped_line:
                yield _sse(data=stopped_marker)
            return

        # 4) Stream output under semaphore
        q_start = time.perf_counter()
        async with GEN_SEMAPHORE:
            try:
                q_wait = time.perf_counter() - q_start
                if isinstance(prep.budget_view, dict):   # type: ignore[attr-defined]
                    prep.budget_view["queueWaitSec"] = round(q_wait, 3)  # type: ignore[attr-defined]
            except Exception:
                pass

            sid = getattr(prep, "session_id", early_sid)
            mark_active(sid, +1)
            log.info("[gen] streaming start sid=%s", sid)
            out_buf = bytearray()

            def _accum_visible(chunk_bytes: bytes):
                if not chunk_bytes:
                    return
                s = chunk_bytes.decode("utf-8", errors="ignore")
                if RUNJSON_START in s and RUNJSON_END in s:
                    # For troubleshooting: record we saw a runjson frame in-flight
                    log.info("[gen] runjson: marker_seen sid=%s", sid)
                    return
                if s.strip() == stopped_marker:
                    return
                out_buf.extend(chunk_bytes)

            # ---- NEW: compute and log the emit gate we pass to the worker/main streamer
            try:
                runjson_emit_setting = bool(SETTINGS.runjson_emit)
                pro_gate = bool(is_request_pro_activated())
                emit_stats_flag = runjson_emit_setting and pro_gate
                log.info(
                    "[gen] emit_check sid=%s runjson_emit=%s pro=%s -> emit_stats=%s",
                    sid, runjson_emit_setting, pro_gate, emit_stats_flag
                )
            except Exception:
                emit_stats_flag = bool(SETTINGS.runjson_emit)

            try:
                async for chunk in run_stream(
                    llm=prep.llm,                       # type: ignore[attr-defined]
                    messages=prep.packed,               # type: ignore[attr-defined]
                    out_budget=prep.out_budget,         # type: ignore[attr-defined]
                    stop_ev=stop_ev,
                    request=request,
                    temperature=prep.temperature,       # type: ignore[attr-defined]
                    top_p=prep.top_p,                   # type: ignore[attr-defined]
                    input_tokens_est=prep.input_tokens_est,   # type: ignore[attr-defined]
                    t0_request=prep.t_request_start,    # type: ignore[attr-defined]
                    budget_view=prep.budget_view,       # type: ignore[attr-defined]
                    emit_stats=emit_stats_flag,         # <- what ultimately governs RUNJSON emission
                ):
                    # Optional: very lightweight peek for markers (helps prove whether upstream appended)
                    if isinstance(chunk, (bytes, bytearray)):
                        s = None
                        try:
                            s = chunk.decode("utf-8", errors="ignore")
                        except Exception:
                            s = None
                        if s and (RUNJSON_START in s or RUNJSON_END in s):
                            log.info("[gen] runjson: chunk_contains_marker sid=%s", sid)
                    _accum_visible(chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode("utf-8"))
                    yield chunk
            finally:
                # Persist clean assistant text (strip RUNJSON)
                try:
                    full_text = out_buf.decode("utf-8", errors="ignore").strip()
                    start = full_text.find(RUNJSON_START)
                    if start != -1:
                        end = full_text.find(RUNJSON_END, start)
                        if end != -1:
                            full_text = (full_text[:start] + full_text[end + len(RUNJSON_END):]).strip()
                    if full_text:
                        prep.st["recent"].append({"role": "assistant", "content": full_text})  # type: ignore[attr-defined]
                except Exception:
                    pass

                try:
                    from ..store import apply_pending_for
                    apply_pending_for(sid)
                except Exception:
                    pass

                try:
                    from ..store import list_messages as store_list_messages
                    from ..workers.retitle_worker import enqueue as enqueue_retitle
                    msgs = store_list_messages(sid)
                    last_seq = max((int(m.id) for m in msgs), default=0)
                    enqueue_retitle(sid, [asdict(m) for m in msgs], job_seq=last_seq)
                except Exception:
                    pass

                mark_active(sid, -1)
                log.info("[gen] streaming end sid=%s", sid)

    return StreamingResponse(
        streamer(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---- cancel endpoints ----

async def cancel_session(session_id: str) -> dict[str, bool]:
    ev = cancel_event(session_id)
    before = ev.is_set()
    ev.set()
    after = ev.is_set()
    log.info("[cancel] set sid=%s ev_id=%s before=%s after=%s", session_id, id(ev), before, after)
    return {"ok": True}


async def cancel_session_alias(session_id: str) -> dict[str, bool]:
    return await cancel_session(session_id)
