# aimodel/file_read/services/generate_flow.py
from __future__ import annotations
import asyncio, time, json
from typing import AsyncGenerator, Dict, List
from fastapi.responses import StreamingResponse
from datetime import datetime

from ..model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody

from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .session_io import handle_incoming, persist_summary
from .packing import build_system_text, pack_with_rollup
from .context_window import clamp_out_budget

# Router + summarizer + orchestrator (web path)
from ..web.router_ai import decide_web
from ..web.query_summarizer import summarize_query
from ..web.orchestrator import build_web_block

# Tell the type checker run_stream is an async iterator of bytes (stops yellow underline)
from .streaming_worker import run_stream as _run_stream
from typing import AsyncIterator
run_stream: (callable[..., AsyncIterator[bytes]]) = _run_stream  # type: ignore[assignment]

# ---- helpers for instrumentation --------------------------------------------
def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")

def _chars_len(msgs: List[object]) -> int:
    """Robust char counter for packed messages that may include dicts or strings."""
    total = 0
    for m in msgs:
        if isinstance(m, dict):
            c = m.get("content")
        else:
            c = m  # plain string (defensive)
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
    """Print the exact payload we send to the model: full messages + key params."""
    try:
        print(f"[{_now()}] PROMPT DUMP BEGIN session={session_id} msgs={len(messages)}")
        print(json.dumps(
            {
                "messages": messages,
                "params": params,
            },
            ensure_ascii=False,
            indent=2,
        ))
        print(f"[{_now()}] PROMPT DUMP END   session={session_id}")
    except Exception as e:
        print(f"[{_now()}] PROMPT DUMP ERROR session={session_id} err={type(e).__name__}: {e}")
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

    # --- ROUTER → (maybe) SUMMARIZER → (maybe) WEB BLOCK ----------------------
    t0 = time.perf_counter()
    print(f"[{_now()}] GEN web_inject START session={session_id} latest_user_text_chars={lut_chars}")
    try:
        need_web, proposed_q = decide_web(llm, str(latest_user_text or ""))
        print(f"[{_now()}] ROUTER decision need_web={need_web} proposed_q={proposed_q!r}")

        if need_web:
            base_query = proposed_q or str(latest_user_text or "")
            q_summary = summarize_query(llm, base_query)
            q_summary = q_summary.strip().strip('"\'')

            print(f"[{_now()}] SUMMARIZER out={q_summary!r}")

            k = int(getattr(data, "webK", 3) or 3)
            print(f"[{_now()}] ORCH build start k={k} q={q_summary!r}")
            block = await build_web_block(q_summary, k=k)
            print(f"[{_now()}] ORCH build done has_block={bool(block)} block_len={(len(block) if block else 0)}")

            if block:
                # CRITICAL: wrap as a proper chat message (dict), not a raw string
                st["_ephemeral_web"] = (st.get("_ephemeral_web") or []) + [
                    {
                        "role": "assistant",
                        # *** ONLY REQUIRED CHANGE: mark findings as authoritative in the content ***
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

    # dump the exact prompt (messages + params) we will send to the model
    _dump_full_prompt(
        packed,
        params={
            "requested_out": out_budget_req,
            "temperature": (data.temperature or 0.6),
            "top_p": (data.top_p or 0.9),
        },
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
                    yield chunk
            finally:
                try:
                    from ..store import apply_pending_for
                    apply_pending_for(session_id)
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
