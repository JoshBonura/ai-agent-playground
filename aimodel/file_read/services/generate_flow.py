# aimodel/file_read/services/generate_flow.py
from __future__ import annotations

import time
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import asdict

from fastapi.responses import StreamingResponse

from ..core.settings import SETTINGS
from ..utils.streaming import RUNJSON_END, RUNJSON_START
from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .streaming_worker import run_stream as _run_stream

run_stream: callable[..., AsyncIterator[bytes]] = _run_stream
from ..core.logging import get_logger

log = get_logger(__name__)
from .generate_pipeline import prepare_generation_with_telemetry


async def generate_stream_flow(data, request) -> StreamingResponse:
    prep = await prepare_generation_with_telemetry(data)
    eff = SETTINGS.effective(session_id=prep.session_id)
    stop_ev = cancel_event(prep.session_id)
    stop_ev.clear()

    async def streamer() -> AsyncGenerator[bytes, None]:
        q_start = time.perf_counter()
        async with GEN_SEMAPHORE:
            try:
                q_wait = time.perf_counter() - q_start
                if isinstance(prep.budget_view, dict):
                    prep.budget_view["queueWaitSec"] = round(q_wait, 3)
            except Exception:
                pass

            mark_active(prep.session_id, +1)
            out_buf = bytearray()

            def _accum_visible(chunk_bytes: bytes):
                if not chunk_bytes:
                    return
                s = chunk_bytes.decode("utf-8", errors="ignore")
                if RUNJSON_START in s and RUNJSON_END in s:
                    return
                if s.strip() == eff["stopped_line_marker"]:
                    return
                out_buf.extend(chunk_bytes)

            try:
                async for chunk in run_stream(
                    llm=prep.llm,
                    messages=prep.packed,
                    out_budget=prep.out_budget,
                    stop_ev=stop_ev,
                    request=request,
                    temperature=prep.temperature,
                    top_p=prep.top_p,
                    input_tokens_est=prep.input_tokens_est,
                    t0_request=prep.t_request_start,
                    budget_view=prep.budget_view,
                ):
                    if isinstance(chunk, (bytes, bytearray)):
                        _accum_visible(chunk)
                    else:
                        _accum_visible(chunk.encode("utf-8"))
                    yield chunk
            finally:
                try:
                    full_text = out_buf.decode("utf-8", errors="ignore").strip()
                    start = full_text.find(RUNJSON_START)
                    if start != -1:
                        end = full_text.find(RUNJSON_END, start)
                        if end != -1:
                            full_text = (
                                full_text[:start] + full_text[end + len(RUNJSON_END) :]
                            ).strip()
                    if full_text:
                        prep.st["recent"].append({"role": "assistant", "content": full_text})
                except Exception:
                    pass

                try:
                    from ..store import apply_pending_for

                    apply_pending_for(prep.session_id)
                except Exception:
                    pass

                try:
                    from ..store import list_messages as store_list_messages
                    from ..workers.retitle_worker import \
                        enqueue as enqueue_retitle

                    msgs = store_list_messages(prep.session_id)
                    last_seq = max((int(m.id) for m in msgs), default=0)
                    enqueue_retitle(prep.session_id, [asdict(m) for m in msgs], job_seq=last_seq)
                except Exception:
                    pass

                mark_active(prep.session_id, -1)

    return StreamingResponse(
        streamer(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def cancel_session(session_id: str) -> dict[str, bool]:
    from .cancel import cancel_event

    cancel_event(session_id).set()
    return {"ok": True}


async def cancel_session_alias(session_id: str) -> dict[str, bool]:
    return await cancel_session(session_id)
