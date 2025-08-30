from __future__ import annotations
import time
import json
from typing import AsyncGenerator, Optional, AsyncIterator
from fastapi.responses import StreamingResponse
from dataclasses import asdict

from ..core.settings import SETTINGS
from ..runtime.model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody

from .cancel import GEN_SEMAPHORE, cancel_event, mark_active
from .session_io import handle_incoming, persist_summary
from .packing import build_system_text, pack_with_rollup
from .context_window import clamp_out_budget

from ..web.router_ai import decide_web_and_fetch
from ..rag.router_ai import decide_rag
from ..rag.retrieve import build_rag_block_session_only
from ..utils.streaming import RUNJSON_START, RUNJSON_END

from .streaming_worker import run_stream as _run_stream
run_stream: (callable[..., AsyncIterator[bytes]]) = _run_stream  # type: ignore[assignment]

# local helpers
from .prompt_utils import now_str, chars_len, dump_full_prompt
from .router_text import compose_router_text
from .attachments import att_get


async def generate_stream_flow(data: ChatBody, request) -> StreamingResponse:
    ensure_ready()
    llm = get_llm()

    # ---- effective settings (no fallbacks) ----
    eff0 = SETTINGS.effective()
    session_id = data.sessionId or eff0["default_session_id"]
    eff = SETTINGS.effective(session_id=session_id)

    if not data.messages:
        return StreamingResponse(
            iter([eff["empty_messages_response"].encode("utf-8")]),
            media_type="text/plain"
        )

    # ---- request params with explicit override only ----
    temperature = float(eff["default_temperature"])
    if getattr(data, "temperature") is not None:
        temperature = float(data.temperature)

    top_p = float(eff["default_top_p"])
    if getattr(data, "top_p") is not None:
        top_p = float(data.top_p)

    out_budget_req = int(eff["default_max_tokens"])
    if getattr(data, "max_tokens") is not None:
        out_budget_req = int(data.max_tokens)

    auto_web = bool(eff["default_auto_web"])
    if getattr(data, "autoWeb") is not None:
        auto_web = bool(data.autoWeb)

    web_k = int(eff["default_web_k"])
    if getattr(data, "webK") is not None:
        web_k = int(data.webK)
    web_k = max(int(eff["web_k_min"]), min(web_k, int(eff["web_k_max"])))

    auto_rag = bool(eff["default_auto_rag"])
    if getattr(data, "autoRag") is not None:
        auto_rag = bool(data.autoRag)

    model_ctx = int(eff["model_ctx"])

    # 🔎 explicit RAG / attachments config print
    print(
        f"[{now_str()}] RAG CONFIG session={session_id} "
        f"param.autoRag={getattr(data, 'autoRag', None)!r} "
        f"default_auto_rag={eff['default_auto_rag']!r} "
        f"-> auto_rag={auto_rag} "
        f"rag_enabled={eff['rag_enabled']!r} "
        f"disable_global_rag_on_attachments={eff['disable_global_rag_on_attachments']!r}"
    )

    # ---- normalize inbound ----
    incoming = [
        {
            "role": m.role,
            "content": m.content,
            "attachments": getattr(m, "attachments", None),  # safe on message objects
        }
        for m in data.messages
    ]
    print(f"[{now_str()}] DEBUG incoming={json.dumps(incoming, default=str, ensure_ascii=False)}")

    latest_user = next((m for m in reversed(incoming) if m["role"] == "user"), {})
    latest_user_text = (latest_user.get("content") or "").strip()
    atts = (latest_user.get("attachments") or [])
    has_atts = bool(atts)

    if not latest_user_text and has_atts:
        names = [att_get(a, "name") for a in atts]
        names = [n for n in names if n]
        latest_user_text = "User uploaded: " + (", ".join(names) if names else "files")
        print(f"[{now_str()}] DEBUG fallback latest_user_text={latest_user_text!r}")
    else:
        print(f"[{now_str()}] DEBUG normal latest_user_text={latest_user_text!r}")

    print(f"[{now_str()}] GEN request START session={session_id} msgs_in={len(incoming)}")
    st = handle_incoming(session_id, incoming)

    # ---- router text once ----
    base_user_text = next((m["content"] for m in reversed(incoming) if m["role"] == "user"), "")
    router_text = compose_router_text(
        st.get("recent", []),
        str(base_user_text or ""),
        st.get("summary", "") or "",
        tail_turns=int(eff["router_tail_turns"]),
        summary_chars=int(eff["router_summary_chars"]),
        max_chars=int(eff["router_max_chars"]),
    )

    # ---------------------- WEB INJECT ----------------------
    t0 = time.perf_counter()
    print(f"[{now_str()}] GEN web_inject START session={session_id} latest_user_text_chars={len(str(base_user_text or ''))}")
    try:
        block = None
        if auto_web and not (has_atts and bool(eff["disable_web_on_attachments"])):
            block = await decide_web_and_fetch(llm, router_text, k=web_k)

        print(f"[{now_str()}] ORCH web has_block={bool(block)} block_len={(len(block) if block else 0)}")

        if block:
            st["_ephemeral_web"] = (st.get("_ephemeral_web") or []) + [{
                "role": "assistant",
                "content": eff["web_block_preamble"] + "\n\n" + block,
            }]

        dt = time.perf_counter() - t0
        eph_cnt = len(st.get("_ephemeral_web") or [])
        print(f"[{now_str()}] GEN web_inject END   session={session_id} elapsed={dt:.3f}s ephemeral_blocks={eph_cnt}")
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"[{now_str()}] GEN web_inject ERROR session={session_id} elapsed={dt:.3f}s err={type(e).__name__}: {e}")

    # ---------------------- ATTACHMENT RETRIEVE (session-only) ----------------
    if has_atts and bool(eff["disable_global_rag_on_attachments"]):
        att_names = [att_get(a, "name") for a in atts if att_get(a, "name")]
        query_for_atts = (base_user_text or "").strip() or " ".join(att_names) or "document"
        print(f"[{now_str()}] ATTACHMENTS retrieve query={query_for_atts!r}")

        try:
            att_block = build_rag_block_session_only(query_for_atts, session_id)
        except Exception as e:
            print(f"[{now_str()}] ATTACHMENTS retrieve ERROR {type(e).__name__}: {e}")
            att_block = None

        if att_block:
            st["_ephemeral_web"] = (st.get("_ephemeral_web") or []) + [{
                "role": "assistant",
                "content": eff["rag_block_preamble"] + "\n\n" + att_block,
            }]
            print(f"[{now_str()}] ATTACHMENTS block injected chars={len(att_block)}")
        else:
            print(f"[{now_str()}] ATTACHMENTS no block injected")

    # ---------------------- PACK (web/attachments ephemeral included) ---------
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

    # ---------------------- RAG ROUTER (normal turns only) --------------------
    rag_router_allowed = not (has_atts and bool(eff["disable_global_rag_on_attachments"]))
    if rag_router_allowed and bool(eff["rag_enabled"]):
        rag_need = False
        rag_query: Optional[str] = None

        if auto_rag:
            try:
                rag_need, rag_query = decide_rag(llm, router_text)
                print(f"[{now_str()}] RAG ROUTER need={rag_need} query={rag_query!r}")
            except Exception as e:
                print(f"[{now_str()}] RAG ROUTER ERROR {type(e).__name__}: {e}")
                # No fallback to settings; be conservative and skip.
                rag_need = False
                rag_query = None

        # If a web block was injected OR RAG router said no, skip RAG
        skip_rag = bool(ephemeral_once) or (not rag_need)

        from .packing import maybe_inject_rag_block
        packed = maybe_inject_rag_block(
            packed,
            session_id=session_id,
            skip_rag=skip_rag,
            rag_query=rag_query,
        )
    else:
        print(f"[{now_str()}] RAG ROUTER skipped (attachment turn or rag_enabled=False)")

    # ---------------------- STREAM SETUP --------------------------------------
    packed_chars = chars_len(packed)
    print(f"[{now_str()}] GEN pack READY session={session_id} msgs={len(packed)} chars={packed_chars} out_budget_req={out_budget_req}")

    dump_full_prompt(
        packed,
        params={"requested_out": out_budget_req, "temperature": temperature, "top_p": top_p},
        session_id=session_id,
    )

    persist_summary(session_id, st["summary"])

    out_budget, input_tokens_est = clamp_out_budget(
        llm=llm, messages=packed, requested_out=out_budget_req, margin=int(eff["clamp_margin"])
    )
    print(f"[{now_str()}] GEN clamp_out_budget session={session_id} out_budget={out_budget} input_tokens_est={input_tokens_est}")

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
                print(f"[{now_str()}] GEN run_stream START session={session_id} msgs={len(packed)} chars={packed_chars} out_budget={out_budget} tokens_in~={input_tokens_est}")
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
                        print(f"[{now_str()}] RECENT append assistant chars={len(full_text)}")
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
                print(f"[{now_str()}] GEN run_stream END session={session_id}")
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
