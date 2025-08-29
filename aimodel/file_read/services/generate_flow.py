# aimodel/file_read/services/generate_flow.py
from __future__ import annotations
import asyncio, time, json
from typing import AsyncGenerator, Dict, List, Optional
from fastapi.responses import StreamingResponse
from datetime import datetime
from dataclasses import asdict

from ..core.settings import SETTINGS
from ..runtime.model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody

from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .session_io import handle_incoming, persist_summary
from .packing import build_system_text, pack_with_rollup, maybe_inject_rag_block
from .context_window import clamp_out_budget

from ..web.router_ai import decide_web_and_fetch
from ..rag.router_ai import decide_rag  # <-- NEW: LLM JSON router for RAG
from ..utils.streaming import RUNJSON_START, RUNJSON_END

from .streaming_worker import run_stream as _run_stream
from typing import AsyncIterator
run_stream: (callable[..., AsyncIterator[bytes]]) = _run_stream  # type: ignore[assignment]


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


def _compose_router_text(
    recent,
    latest_user_text: str,
    summary: str,
    *,
    tail_turns: Optional[int] = None,
    summary_chars: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    eff = SETTINGS.effective()
    tt = int(eff["router_tail_turns"]) if tail_turns is None else int(tail_turns)
    sc = int(eff["router_summary_chars"]) if summary_chars is None else int(summary_chars)
    mc = int(eff["router_max_chars"]) if max_chars is None else int(max_chars)
    context_label = eff["router_context_label"]
    summary_label = eff["router_summary_label"]

    parts: List[str] = []
    if latest_user_text:
        parts.append((latest_user_text or "").strip())

    try:
        recent_list = list(recent)
    except Exception:
        recent_list = []

    tail_src = recent_list[-tt:] if tt > 0 else []
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
        parts.append(context_label + "\n" + "\n".join(tail_lines))

    if summary:
        s = summary.strip()
        if sc > 0 and len(s) > sc:
            s = s[-sc:]
        parts.append(summary_label + "\n" + s)

    out = "\n\n".join(parts).strip()
    if len(out) > mc:
        out = out[:mc].rstrip()
    return out


async def generate_stream_flow(data: ChatBody, request) -> StreamingResponse:
    ensure_ready()
    llm = get_llm()

    eff0 = SETTINGS.effective()
    session_id = data.sessionId or eff0["default_session_id"]
    eff = SETTINGS.effective(session_id=session_id)

    if not data.messages:
        return StreamingResponse(iter([eff["empty_messages_response"].encode("utf-8")]), media_type="text/plain")

    temperature = data.temperature if getattr(data, "temperature", None) is not None else float(eff["default_temperature"])
    top_p = data.top_p if getattr(data, "top_p", None) is not None else float(eff["default_top_p"])
    out_budget_req = int(data.max_tokens) if getattr(data, "max_tokens", None) is not None else int(eff["default_max_tokens"])

    auto_web = data.autoWeb if getattr(data, "autoWeb", None) is not None else bool(eff["default_auto_web"])
    web_k = int(data.webK) if getattr(data, "webK", None) is not None else int(eff["default_web_k"])
    web_k = max(int(eff["web_k_min"]), min(web_k, int(eff["web_k_max"])))

    model_ctx = int(eff["model_ctx"])

    incoming = [{"role": m.role, "content": m.content} for m in data.messages]
    print(f"[{_now()}] GEN request START session={session_id} msgs_in={len(incoming)}")

    st = handle_incoming(session_id, incoming)

    latest_user_text = next((m["content"] for m in reversed(incoming) if m["role"] == "user"), "")
    lut_chars = len(latest_user_text) if isinstance(latest_user_text, str) else len(str(latest_user_text) or "")

    # ---------------------- WEB INJECT (optional) ----------------------
    t0 = time.perf_counter()
    print(f"[{_now()}] GEN web_inject START session={session_id} latest_user_text_chars={lut_chars}")
    try:
        block = None
        router_text = _compose_router_text(
            st.get("recent", []),
            str(latest_user_text or ""),
            st.get("summary", "") or "",
            tail_turns=int(eff["router_tail_turns"]),
            summary_chars=int(eff["router_summary_chars"]),
            max_chars=int(eff["router_max_chars"]),
        )

        if auto_web:
            block = await decide_web_and_fetch(llm, router_text, k=web_k)

        print(f"[{_now()}] ORCH build done has_block={bool(block)} block_len={(len(block) if block else 0)}")

        if block:
            st["_ephemeral_web"] = (st.get("_ephemeral_web") or []) + [
                {
                    "role": "assistant",
                    "content": eff["web_block_preamble"] + "\n\n" + block,
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

    # ---------------------- PACK (with ephemeral web) ----------------------
    system_text = build_system_text()

    ephemeral_once = st.pop("_ephemeral_web", [])
    packed, st["summary"], _ = pack_with_rollup(
        system_text=system_text,
        summary=st["summary"],
        recent=st["recent"],
        max_ctx=model_ctx,
        out_budget=out_budget_req,
        ephemeral=ephemeral_once,
    )

    # ---------------------- RAG ROUTER (LLM JSON) ----------------------
    rag_need = False
    rag_query: Optional[str] = None
    try:
        rag_need, rag_query = decide_rag(llm, router_text)
        print(f"[{_now()}] RAG ROUTER need={rag_need} query={rag_query!r}")
    except Exception as e:
        print(f"[{_now()}] RAG ROUTER ERROR {type(e).__name__}: {e}")
        rag_need = bool(SETTINGS.effective().get("rag_default_need_when_invalid", False))
        rag_query = None

    # If a web block was injected OR RAG router said no, skip RAG
    skip_rag = bool(ephemeral_once) or (not rag_need)

    # Optionally pass LLM-refined query to RAG
    packed = maybe_inject_rag_block(
        packed,
        session_id=session_id,
        skip_rag=skip_rag,
        rag_query=rag_query,
    )

    # ---------------------- STREAM SETUP ----------------------
    packed_chars = _chars_len(packed)
    print(f"[{_now()}] GEN pack READY       session={session_id} msgs={len(packed)} chars={packed_chars} out_budget_req={out_budget_req}")

    _dump_full_prompt(
        packed,
        params={
            "requested_out": out_budget_req,
            "temperature": temperature,
            "top_p": top_p,
        },
        session_id=session_id,
    )

    persist_summary(session_id, st["summary"])

    out_budget, input_tokens_est = clamp_out_budget(
        llm=llm, messages=packed, requested_out=out_budget_req, margin=int(eff["clamp_margin"])
    )
    print(f"[{_now()}] GEN clamp_out_budget  session={session_id} out_budget={out_budget} input_tokens_est={input_tokens_est}")

    stop_ev = cancel_event(session_id)
    stop_ev.clear()

    async def streamer() -> AsyncGenerator[bytes, None]:
        async with GEN_SEMAPHORE:
            mark_active(session_id, +1)
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
                print(f"[{_now()}] GEN run_stream START session={session_id} msgs={len(packed)} chars={packed_chars} out_budget={out_budget} tokens_in~={input_tokens_est}")
                async for chunk in run_stream(
                    llm=llm,
                    messages=packed,
                    out_budget=out_budget,
                    stop_ev=stop_ev,
                    request=request,
                    temperature=temperature,
                    top_p=top_p,
                    input_tokens_est=input_tokens_est,
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
                            full_text = (full_text[:start] + full_text[end + len(RUNJSON_END):]).strip()
                    if full_text:
                        st["recent"].append({"role": "assistant", "content": full_text})
                        print(f"[{_now()}] RECENT append assistant chars={len(full_text)}")
                except Exception:
                    pass
                try:
                    from ..store import apply_pending_for
                    apply_pending_for(session_id)
                except Exception:
                    pass
                try:
                    from ..store import list_messages as store_list_messages
                    from ..workers.retitle_worker import enqueue as enqueue_retitle
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
