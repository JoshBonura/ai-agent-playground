# aimodel/file_read/services/generate_flow.py
from __future__ import annotations
import asyncio, time, json
from typing import AsyncGenerator, Dict, List
from fastapi.responses import StreamingResponse
from datetime import datetime
from dataclasses import asdict  # for serializing message rows

from ..model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody

from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .session_io import handle_incoming, persist_summary
from .packing import build_system_text, pack_with_rollup
from .context_window import clamp_out_budget

# Router (router will decide & fetch if needed)
from ..web.router_ai import decide_web_and_fetch

# Stream meta markers to filter out from the buffered assistant text
from ..utils.streaming import RUNJSON_START, RUNJSON_END

# Tell the type checker run_stream is an async iterator of bytes (stops yellow underline)
from .streaming_worker import run_stream as _run_stream
from typing import AsyncIterator
run_stream: (callable[..., AsyncIterator[bytes]]) = _run_stream  # type: ignore[assignment]

# ---- helpers for instrumentation --------------------------------------------
def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")

def _chars_len(msgs: List[object]) -> int:
    total = 0
    for m in msgs:
        if isinstance(m, dict):
            c = m.get("content")
        else:
            c = m
        if isinstance(c, str):
            total += len(c)
        elif c is None:
            continue
        else:
            try:
                total += len(json.dumps(c, ensure_ascii=False))
            except Exception:
                pass
    return total

def _dump_full_prompt(messages: List[Dict[str, object]], *, params: Dict[str, object], session_id: str) -> None:
    try:
        print(f"[{_now()}] PROMPT DUMP BEGIN session={session_id} msgs={len(messages)}")
        print(json.dumps({"messages": messages, "params": params}, ensure_ascii=False, indent=2))
        print(f"[{_now()}] PROMPT DUMP END   session={session_id}")
    except Exception as e:
        print(f"[{_now()}] PROMPT DUMP ERROR session={session_id} err={type(e).__name__}: {e}")

# ---- tiny helper: last user + recent tail (user & assistant) + summary -------
def _compose_router_text(
    recent,
    latest_user_text: str,
    summary: str,
    *,
    tail_turns: int = 6,
    summary_chars: int = 600,
    max_chars: int = 1400,
    
) -> str:
    """
    Priority input for the router:
      1) Latest user message (verbatim)
      2) Short recent tail (user + assistant) so URLs/snippets are visible
      3) Trimmed slice of the persisted conversation summary

    Hard-caps the final text to max_chars to avoid overfeeding the router.
    """
    parts: List[str] = []

    if latest_user_text:
        parts.append((latest_user_text or "").strip())

    # Convert to list for safe slicing; include both roles
    try:
        recent_list = list(recent)
    except Exception:
        recent_list = []

    tail_src = recent_list[-tail_turns:]
    tail_lines: List[str] = []
    for m in reversed(tail_src):
        if not isinstance(m, dict):
            continue
        c = (m.get("content") or "").strip()
        if not c:
            continue
        role = (m.get("role") or "user").strip()
        tail_lines.append(f"{role}: {c}")

    if tail_lines:
        parts.append("Context:\n" + "\n".join(tail_lines))

    if summary:
        s = summary.strip()
        if len(s) > summary_chars:
            s = s[-summary_chars:]  # take the most recent slice of the summary
        parts.append("Summary:\n" + s)

    out = "\n\n".join(parts).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out

# -----------------------------------------------------------------------------

async def generate_stream_flow(data: ChatBody, request) -> StreamingResponse:
    ensure_ready()
    llm = get_llm()

    session_id = data.sessionId or "default"
    if not data.messages:
        return StreamingResponse(iter([b"No messages provided."]), media_type="text/plain")

    incoming = [{"role": m.role, "content": m.content} for m in data.messages]
    print(f"[{_now()}] GEN request START session={session_id} msgs_in={len(incoming)}")

    st = handle_incoming(session_id, incoming)

    # latest user text from THIS request only
    latest_user_text = next((m["content"] for m in reversed(incoming) if m["role"] == "user"), "")
    lut_chars = len(latest_user_text) if isinstance(latest_user_text, str) else len(str(latest_user_text) or "")

    # --- ROUTER (one-hop) → maybe WEB BLOCK -----------------------------------
    t0 = time.perf_counter()
    print(f"[{_now()}] GEN web_inject START session={session_id} latest_user_text_chars={lut_chars}")
    try:
        k = int(getattr(data, "webK", 3) or 3)

        # Minimal change: give the router a compact view (last user + tail + summary)
        router_text = _compose_router_text(
            st.get("recent", []),
            str(latest_user_text or ""),
            st.get("summary", "") or "", tail_turns=0,summary_chars=0, 
        )
        block = await decide_web_and_fetch(llm, router_text, k=k)

        print(f"[{_now()}] ORCH build done has_block={bool(block)} block_len={(len(block) if block else 0)}")

        if block:
            st["_ephemeral_web"] = (st.get("_ephemeral_web") or []) + [
                {
                    "role": "assistant",
                    "content": "Web findings (authoritative — use these to answer accurately; override older knowledge):\n\n" + block,
                }
            ]
            types_preview = [type(x).__name__ for x in (st.get("_ephemeral_web") or [])]
            print(f"[{_now()}] EPHEMERAL attached count={len(st['_ephemeral_web'])} types={types_preview}")

        dt = time.perf_counter() - t0
        eph_cnt = len(st.get("_ephemeral_web") or [])
        print(f"[{_now()}] GEN web_inject END   session={session_id} elapsed={dt:.3f}s ephemeral_blocks={eph_cnt}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"[{_now()}] GEN web_inject ERROR session={session_id} elapsed={dt:.3f}s err={type(e).__name__}: {e}")

    out_budget_req = data.max_tokens or 512
    system_text = build_system_text()

    # consume ephemeral web block so it doesn't stick across turns
    ephemeral_once = st.pop("_ephemeral_web", [])
    packed, st["summary"], _ = pack_with_rollup(
        system_text=system_text,
        summary=st["summary"],
        recent=st["recent"],
        max_ctx=4096,
        out_budget=out_budget_req,
        ephemeral=ephemeral_once,
        
    )

    packed_chars = _chars_len(packed)
    print(f"[{_now()}] GEN pack READY       session={session_id} msgs={len(packed)} chars={packed_chars} out_budget_req={out_budget_req}")

    _dump_full_prompt(
        packed,
        params={"requested_out": out_budget_req, "temperature": (data.temperature or 0.6), "top_p": (data.top_p or 0.9)},
        session_id=session_id,
    )

    persist_summary(session_id, st["summary"])

    out_budget, input_tokens_est = clamp_out_budget(
        llm=llm, messages=packed, requested_out=out_budget_req, margin=32
    )
    print(f"[{_now()}] GEN clamp_out_budget  session={session_id} out_budget={out_budget} input_tokens_est={input_tokens_est}")

    stop_ev = cancel_event(session_id)
    stop_ev.clear()

    async def streamer() -> AsyncGenerator[bytes, None]:
        async with GEN_SEMAPHORE:
            mark_active(session_id, +1)
            # Buffer the assistant text we stream so we can add it to st["recent"]
            out_buf = bytearray()

            def _accum_visible(chunk_bytes: bytes):
                if not chunk_bytes:
                    return
                s = chunk_bytes.decode("utf-8", errors="ignore")
                # Skip embedded run-json envelopes entirely
                if RUNJSON_START in s and RUNJSON_END in s:
                    return
                # Skip the “stopped” line if present
                if s.strip() == "⏹ stopped":
                    return
                out_buf.extend(chunk_bytes)

            try:
                print(f"[{_now()}] GEN run_stream START session={session_id} msgs={len(packed)} chars={packed_chars} out_budget={out_budget} tokens_in~={input_tokens_est}")
                async for chunk in run_stream(
                    llm=llm,
                    messages=packed,
                    out_budget=out_budget,
                    stop_ev=stop_ev,
                    request=request,
                    temperature=(data.temperature or 0.6),
                    top_p=(data.top_p or 0.9),
                    input_tokens_est=input_tokens_est,
                ):
                    # accumulate for router/model future context
                    if isinstance(chunk, (bytes, bytearray)):
                        _accum_visible(chunk)
                    else:
                        _accum_visible(chunk.encode("utf-8"))
                    yield chunk
            finally:
                # Append the assistant’s full response to recent so both router and model
                # will see it on the next turn.
                try:
                    full_text = out_buf.decode("utf-8", errors="ignore").strip()
                    # hard-strip any trailing RUNJSON block that slipped through
                    start = full_text.find(RUNJSON_START)
                    if start != -1:
                        end = full_text.find(RUNJSON_END, start)
                        if end != -1:
                            full_text = (full_text[:start] + full_text[end + len(RUNJSON_END):]).strip()
                    if full_text:
                        st["recent"].append({"role": "assistant", "content": full_text})
                        print(f"[{_now()}] RECENT append assistant chars={len(full_text)}")
                except Exception:
                    pass

                # 1) flush pending ops
                try:
                    from ..store import apply_pending_for
                    apply_pending_for(session_id)
                except Exception:
                    pass

                # 2) enqueue retitle AFTER the stream has fully finished (coalesced, with watermark)
                try:
                    from ..store import list_messages as store_list_messages
                    from ..retitle_worker import enqueue as enqueue_retitle
                    msgs = store_list_messages(session_id)
                    last_seq = max((int(m.id) for m in msgs), default=0)
                    enqueue_retitle(session_id, [asdict(m) for m in msgs], job_seq=last_seq)
                except Exception:
                    pass

                print(f"[{_now()}] GEN run_stream END   session={session_id}")
                mark_active(session_id, -1)

    return StreamingResponse(
        streamer(),
        media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

async def cancel_session(session_id: str):
    from .cancel import cancel_event
    cancel_event(session_id).set()
    return {"ok": True}

async def cancel_session_alias(session_id: str):
    return await cancel_session(session_id)
