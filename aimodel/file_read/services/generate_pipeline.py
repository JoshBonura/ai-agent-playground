# aimodel/file_read/services/generate_pipeline.py
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.logging import get_logger

log = get_logger(__name__)

from ..core.packing_memory_core import PACK_TELEMETRY
from ..core.schemas import ChatBody
from ..core.settings import SETTINGS
from ..rag.retrieve_pipeline import build_rag_block_session_only_with_telemetry
from ..runtime.model_runtime import ensure_ready, get_llm
from ..web.router_ai import decide_web_and_fetch
from .attachments import att_get
from .generate_pipeline_part2 import _finish_prepare_generation_with_telemetry
from .generate_pipeline_support import Prep, _approx_block_tokens, _bool, PrepCancelled
from .packing import build_system_text, pack_with_rollup
from .router_text import compose_router_text
from .session_io import handle_incoming
from ..deps.license_deps import is_request_pro_activated


async def _yield_if_stopping(stop_ev: asyncio.Event | None, where: str, *, hard: bool = False) -> None:
    """Cooperative checkpoint: optionally raise to hard-cancel PREP."""
    if stop_ev and stop_ev.is_set():
        log.info("[PIPE] stop observed at %s", where)
        if hard:
            raise PrepCancelled(where)
    # Let the event loop breathe so other tasks (like cancel handler) can run:
    await asyncio.sleep(0)


async def prepare_generation_with_telemetry(
    data: ChatBody,
    stop_ev: asyncio.Event | None = None,  # injected from generate_flow
) -> Prep:
    # Model readiness & handle early cancel
    ensure_ready()
    await _yield_if_stopping(stop_ev, "ensure_ready.done", hard=True)

    llm = get_llm()
    await _yield_if_stopping(stop_ev, "get_llm.done", hard=True)

    t_request_start = time.perf_counter()
    eff0 = SETTINGS.effective()
    session_id = data.sessionId or eff0["default_session_id"]
    eff = SETTINGS.effective(session_id=session_id)

    rag_global_enabled = bool(eff.get("rag_global_enabled", True))
    rag_session_enabled = bool(eff.get("rag_session_enabled", True))
    force_session_only = bool(eff.get("rag_force_session_only")) or not rag_global_enabled

    temperature = float(eff["default_temperature"] if data.temperature is None else data.temperature)
    top_p = float(eff["default_top_p"] if data.top_p is None else data.top_p)
    out_budget_req = int(eff["default_max_tokens"] if data.max_tokens is None else data.max_tokens)

    auto_web = _bool(eff["default_auto_web"]) if data.autoWeb is None else _bool(data.autoWeb)
    web_k = int(eff["default_web_k"] if data.webK is None else data.webK)
    web_k = max(int(eff["web_k_min"]), min(web_k, int(eff["web_k_max"])))

    auto_rag = _bool(eff["default_auto_rag"]) if data.autoRag is None else _bool(data.autoRag)
    model_ctx = int(eff["model_ctx"])

    # ---- Pro + Activation gate for both Web & RAG (no admin required) ----
    entitled = bool(is_request_pro_activated())
    allow_web = entitled
    allow_rag = entitled

    rag_global_enabled = bool(rag_global_enabled and entitled)
    rag_session_enabled = bool(rag_session_enabled and entitled)
    auto_rag = bool(auto_rag and entitled)
    auto_web = bool(auto_web and entitled)
    # ----------------------------------------------------------------------

    incoming = [
        {"role": m.role, "content": m.content, "attachments": getattr(m, "attachments", None)}
        for m in data.messages or []
    ]
    log.info(f"[PIPE] incoming_msgs={len(incoming)}")

    latest_user = next((m for m in reversed(incoming) if m["role"] == "user"), {})
    latest_user_text = (latest_user.get("content") or "").strip()
    atts = latest_user.get("attachments") or []
    has_atts = bool(atts)
    log.info(
        f"[PIPE] latest_user_text_len={len(latest_user_text)} has_atts={has_atts} att_count={len(atts)}"
    )
    if not latest_user_text and has_atts:
        names = [att_get(a, "name") for a in atts]
        names = [n for n in names if n]
        latest_user_text = "User uploaded: " + (", ".join(names) if names else "files")

    st = handle_incoming(session_id, incoming)
    base_user_text = next((m["content"] for m in reversed(incoming) if m["role"] == "user"), "")

    router_text = compose_router_text(
        st.get("recent", []),
        str(base_user_text or ""),
        st.get("summary", "") or "",
        tail_turns=int(eff["router_tail_turns"]),
        summary_chars=int(eff["router_summary_chars"]),
        max_chars=int(eff["router_max_chars"]),
    )
    await _yield_if_stopping(stop_ev, "router_text.ready", hard=True)

    telemetry: dict[str, Any] = {
        "web": {},
        "rag": {},
        "pack": {},
        "prepSec": round(time.perf_counter() - t_request_start, 6),
    }

    ephemeral_once: list[dict[str, str]] = []
    telemetry["web"]["injectElapsedSec"] = 0.0
    telemetry["web"]["ephemeralBlocks"] = 0

    # ---------------------
    # WEB: decide + fallback
    # ---------------------
    try:
        web_block: str | None = None
        web_tel: dict[str, Any] = {}

        if (
            auto_web
            and allow_web
            and not (has_atts and bool(eff.get("disable_global_rag_on_attachments")))
        ):
            # Can be slow — allow immediate cancel around it
            await _yield_if_stopping(stop_ev, "web.decide_fetch.start", hard=True)
            res = await decide_web_and_fetch(llm, router_text, k=web_k)
            await _yield_if_stopping(stop_ev, "web.decide_fetch.done", hard=True)

            if isinstance(res, tuple):
                web_block = res[0] if len(res) > 0 else None
                tel_candidate = res[1] if len(res) > 1 else None
                if isinstance(tel_candidate, dict):
                    web_tel = tel_candidate
            elif isinstance(res, str):
                web_block = res
            else:
                web_block = None

        telemetry["web"].update(web_tel or {})
        need_flag = (web_tel or {}).get("needed")
        injected_candidate = isinstance(web_block, str) and bool(web_block.strip())

        if need_flag is True and (not injected_candidate) and allow_web:
            try:
                from ..web.orchestrator import build_web_block

                await _yield_if_stopping(stop_ev, "web.orchestrator.start", hard=True)
                fb, fb_tel = await build_web_block(router_text, k=web_k)
                await _yield_if_stopping(stop_ev, "web.orchestrator.done", hard=True)

                log.info(
                    f"[PIPE][WEB] orchestrator block preview: {fb[:200]!r}"
                    if fb
                    else "[PIPE][WEB] orchestrator returned no block"
                )
                log.info(f"[PIPE][WEB] orchestrator telemetry: {fb_tel}")
                if fb and fb.strip():
                    web_block = fb
                    injected_candidate = True
            except Exception as e:
                log.error(f"[PIPE][WEB] orchestrator fallback error: {e}")

        if injected_candidate:
            t0_inject = time.perf_counter()
            web_text = str(eff["web_block_preamble"]) + "\n\n" + web_block.strip()
            max_chars = int(eff.get("web_inject_max_chars") or 0)
            if max_chars > 0 and len(web_text) > max_chars:
                web_text = web_text[:max_chars]
            telemetry["web"]["blockChars"] = len(web_text)
            tok = _approx_block_tokens(llm, "assistant", web_text)
            if tok is not None:
                telemetry["web"]["blockTokensApprox"] = tok
            telemetry["web"]["injected"] = True
            ephemeral_only = bool(eff.get("web_ephemeral_only", True))
            telemetry["web"]["ephemeral"] = ephemeral_only
            telemetry["web"]["droppedFromSummary"] = ephemeral_only
            PACK_TELEMETRY["ignore_ephemeral_in_summary"] = ephemeral_only

            # checkpoint before mutating packed state
            await _yield_if_stopping(stop_ev, "web.inject.prepend", hard=True)
            ephemeral_once.append(
                {
                    "role": "assistant",
                    "content": web_text,
                    "_ephemeral": True if ephemeral_only else False,
                    "_source": "web",
                }
            )
            telemetry["web"]["injectElapsedSec"] = round(time.perf_counter() - t0_inject, 6)
        else:
            telemetry["web"]["injected"] = False
            telemetry["web"]["injectElapsedSec"] = 0.0
    except PrepCancelled:
        # Bubble up unchanged
        raise
    except Exception as e:
        log.error(f"[PIPE][WEB] error: {e}")
        telemetry["web"].setdefault("injected", False)
        telemetry["web"].setdefault("injectElapsedSec", 0.0)

    telemetry["web"]["ephemeralBlocks"] = len(ephemeral_once)
    await _yield_if_stopping(stop_ev, "web.phase.done", hard=True)

    log.info(
        f"[PIPE] has_atts={has_atts} disable_global_rag_on_attachments={bool(eff.get('disable_global_rag_on_attachments'))}"
    )

    # ---------------------
    # RAG: session-only path on attachments
    # ---------------------
    if allow_rag and has_atts and bool(eff.get("disable_global_rag_on_attachments")):
        att_names = [att_get(a, "name") for a in atts if att_get(a, "name")]
        query_for_atts = (base_user_text or "").strip() or " ".join(att_names) or "document"
        log.info(
            f"[PIPE] session-only RAG path query_for_atts={query_for_atts!r} att_names={att_names}"
        )
        t0_att = time.perf_counter()
        try:
            await _yield_if_stopping(stop_ev, "rag.session_only.start", hard=True)
            att_block, att_tel = build_rag_block_session_only_with_telemetry(
                query_for_atts, session_id
            )
            await _yield_if_stopping(stop_ev, "rag.session_only.done", hard=True)

            log.info(f"[PIPE][RAG] session-only query: {query_for_atts!r}")
            log.info(
                f"[PIPE][RAG] session-only block preview: {att_block[:200]!r}"
                if att_block
                else "[PIPE][RAG] no session-only block"
            )
        except PrepCancelled:
            raise
        except Exception:
            att_block, att_tel = (None, {})
        if att_tel:
            telemetry["rag"].update(att_tel)
        log.info(
            f"[PIPE] session-only RAG built={bool(att_block)} block_chars={len(att_block or '')}"
        )
        if att_block:
            rag_text = str(eff["rag_block_preamble"]) + "\n\n" + att_block
            telemetry["rag"]["sessionOnly"] = True
            telemetry["rag"]["mode"] = "session-only"
            telemetry["rag"]["blockChars"] = len(rag_text)
            tok = _approx_block_tokens(llm, "assistant", rag_text)
            if tok is not None:
                telemetry["rag"]["sessionOnlyTokensApprox"] = tok
            telemetry["rag"]["injected"] = True

            await _yield_if_stopping(stop_ev, "rag.session_only.inject", hard=True)
            ephemeral_once.append({"role": "assistant", "content": rag_text, "_ephemeral": True})
        else:
            telemetry["rag"]["sessionOnly"] = False
            telemetry["rag"].setdefault("injected", False)
        telemetry["rag"]["sessionOnlyBuildSec"] = round(time.perf_counter() - t0_att, 6)

    # ---------------------
    # PACK messages (can be heavy)
    # ---------------------
    system_text = build_system_text()
    await _yield_if_stopping(stop_ev, "pack.prep", hard=True)

    t_pack0 = time.perf_counter()
    packed, st["summary"], _ = pack_with_rollup(
        system_text=system_text,
        summary=st["summary"],
        recent=st["recent"],
        max_ctx=model_ctx,
        out_budget=out_budget_req,
        ephemeral=ephemeral_once,
    )
    telemetry["packSec"] = round(time.perf_counter() - t_pack0, 6)
    await _yield_if_stopping(stop_ev, "pack.done", hard=True)

    # Hand off to part2; propagate stop_ev for more checkpoints there
    return await _finish_prepare_generation_with_telemetry(
        llm,
        eff,
        data,
        st,
        router_text,
        latest_user_text,
        base_user_text,
        has_atts,
        force_session_only,
        rag_session_enabled,
        rag_global_enabled,
        auto_rag,
        telemetry,
        packed,
        out_budget_req,
        temperature,
        top_p,
        t_request_start,
        session_id,
        stop_ev=stop_ev,  # pass through
    )
