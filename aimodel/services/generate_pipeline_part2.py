# aimodel/file_read/services/generate_pipeline_part2.py
from __future__ import annotations

import asyncio
import time

from ..core.logging import get_logger

log = get_logger(__name__)

from ..core.packing_memory_core import PACK_TELEMETRY
from ..rag.router_ai import decide_rag
from .budget import analyze_budget
from .context_window import clamp_out_budget
from .generate_pipeline_support import (
    Prep,
    _approx_block_tokens,
    _diff_find_inserted_block,
    _enforce_fit,
    _tok_count,
    _web_breakdown,
    _web_unattributed,
)
from .packing import maybe_inject_rag_block
from .prompt_utils import chars_len
from .session_io import persist_summary
from .generate_pipeline_support import PrepCancelled # ← hard-cancel signal from part1


async def _yield_if_stopping(
    stop_ev: asyncio.Event | None,
    where: str,
    *,
    hard: bool = False,
) -> None:
    """Cooperative checkpoint; optionally raise to abort PREP immediately."""
    if stop_ev and stop_ev.is_set():
        log.info("[PIPE] stop observed at %s", where)
        if hard:
            raise PrepCancelled(where)
    await asyncio.sleep(0)


async def _finish_prepare_generation_with_telemetry(
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
    *,
    stop_ev: asyncio.Event | None = None,  # ← propagated from PREP
) -> Prep:
    must_inject_session = bool(
        force_session_only
        and rag_session_enabled
        and (not has_atts)
        and (not telemetry.get("web", {}).get("ephemeralBlocks"))
    )
    rag_router_allowed = (
        (rag_session_enabled or rag_global_enabled)
        and (not (has_atts and bool(eff["disable_global_rag_on_attachments"])))
    ) or must_inject_session

    web_needed = bool((telemetry.get("web") or {}).get("needed"))
    web_injected = bool((telemetry.get("web") or {}).get("injected"))
    if web_needed or web_injected:
        rag_router_allowed = False
        telemetry.setdefault("rag", {})
        telemetry["rag"]["routerSkipped"] = True
        telemetry["rag"]["routerSkippedReason"] = (
            "web_needed" if web_needed else "web_block_present"
        )

    ephemeral_once: list[dict[str, str]] = []

    # ---------------------
    # RAG Router + Inject
    # ---------------------
    if rag_router_allowed and bool(eff["rag_enabled"]) and (not ephemeral_once):
        rag_need = False
        rag_query: str | None = None
        if must_inject_session:
            rag_need = True
            rag_query = (latest_user_text or base_user_text or "").strip()
            telemetry["rag"]["routerDecideSec"] = 0.0
            telemetry["rag"]["routerNeeded"] = True
            telemetry["rag"]["routerForcedSession"] = True
            telemetry["rag"]["routerQuery"] = rag_query
        else:
            t_router0 = time.perf_counter()
            if auto_rag:
                await _yield_if_stopping(stop_ev, "rag.router.start", hard=True)
                try:
                    rag_need, rag_query = decide_rag(llm, router_text)
                except Exception:
                    rag_need, rag_query = (False, None)
                await _yield_if_stopping(stop_ev, "rag.router.done", hard=True)
            telemetry["rag"]["routerDecideSec"] = round(time.perf_counter() - t_router0, 6)
            telemetry["rag"]["routerNeeded"] = bool(rag_need)
            if rag_query is not None:
                telemetry["rag"]["routerQuery"] = rag_query

        skip_rag = bool(ephemeral_once) or not rag_need
        tokens_before = _tok_count(llm, packed)

        t_inject0 = time.perf_counter()
        log.info(f"[PIPE][RAG] router query: {rag_query!r} skip_rag={skip_rag}")

        await _yield_if_stopping(stop_ev, "rag.inject.start", hard=True)
        res = maybe_inject_rag_block(
            packed,
            session_id=session_id,
            skip_rag=skip_rag,
            rag_query=rag_query,
            force_session_only=force_session_only,
        )
        await _yield_if_stopping(stop_ev, "rag.inject.done", hard=True)

        telemetry["rag"]["injectBuildSec"] = round(time.perf_counter() - t_inject0, 6)

        if isinstance(res, tuple):
            packed2 = res[0]
            tel = res[1] if len(res) > 1 and isinstance(res[1], dict) else {}
            block_text = res[2] if len(res) > 2 and isinstance(res[2], str) else None
        else:
            packed2 = res
            tel = {}
            block_text = None

        if tel:
            telemetry["rag"].update(tel)

        if block_text:
            log.debug(f"[PIPE][RAG] injected block preview: {block_text[:200]!r}")
            telemetry["rag"]["blockChars"] = len(block_text)
            tok = _approx_block_tokens(llm, "user", block_text)
            if tok is not None:
                telemetry["rag"]["blockTokensApprox"] = tok
            telemetry["rag"]["injected"] = True
            telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or (
                "session-only" if force_session_only else "global"
            )
        else:
            inserted = _diff_find_inserted_block(packed, packed2)
            if inserted and isinstance(inserted.get("content"), str):
                log.debug(f"[PIPE][RAG] diff-inserted block preview: {inserted['content'][:200]!r}")
                text = inserted["content"]
                telemetry["rag"]["blockChars"] = len(text)
                tok = _approx_block_tokens(llm, "user", text)
                if tok is not None:
                    telemetry["rag"]["blockTokensApprox"] = tok
                telemetry["rag"]["injected"] = True
                telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or (
                    "session-only" if force_session_only else "global"
                )

        tokens_after = _tok_count(llm, packed2)
        if tokens_before is not None:
            telemetry["rag"]["packedTokensBefore"] = tokens_before
        if tokens_after is not None:
            telemetry["rag"]["packedTokensAfter"] = tokens_after
        if tokens_before is not None and tokens_after is not None:
            telemetry["rag"]["ragTokensAdded"] = max(0, tokens_after - tokens_before)

        packed = packed2
    else:
        telemetry.setdefault("rag", {})
        telemetry["rag"]["routerSkipped"] = True
        if telemetry.get("web", {}).get("ephemeralBlocks"):
            telemetry["rag"]["routerSkippedReason"] = "ephemeral_block_present"
        elif not rag_router_allowed:
            telemetry["rag"]["routerSkippedReason"] = "attachments_disable_global_or_rag_disabled"
        elif not bool(eff["rag_enabled"]):
            telemetry["rag"]["routerSkippedReason"] = "rag_disabled"
        log.info(f"[PIPE] rag_router_skipped reason={telemetry['rag'].get('routerSkippedReason')}")

    await _yield_if_stopping(stop_ev, "rag.phase.done", hard=True)

    # ---------------------
    # Fit / Budget / Summaries
    # ---------------------
    packed, out_budget_adj = _enforce_fit(llm, eff, packed, out_budget_req)
    await _yield_if_stopping(stop_ev, "fit.done", hard=True)

    packed_chars = chars_len(packed)
    telemetry["packedChars"] = packed_chars
    telemetry["messages"] = len(packed)

    # ---- pull PackTel -> telemetry['pack'] (+ optional legacy mirrors) ----
    try:
        pack_tel = PACK_TELEMETRY.model_dump()  # Pydantic v2
    except AttributeError:
        pack_tel = PACK_TELEMETRY.dict()  # Pydantic v1

    telemetry.setdefault("pack", {}).update(pack_tel)

    for k in (
        "summarySec",
        "summaryTokensApprox",
        "summaryUsedLLM",
        "finalTrimSec",
        "compressSec",
        "packInputTokensApprox",
        "packMsgs",
        "finalTrimTokensBefore",
        "finalTrimTokensAfter",
        "finalTrimDroppedMsgs",
        "finalTrimDroppedApproxTokens",
        "finalTrimSummaryShrunkFromChars",
        "finalTrimSummaryShrunkToChars",
        "finalTrimSummaryDroppedChars",
        "rollStartTokens",
        "rollOverageTokens",
    ):
        telemetry[k] = pack_tel.get(k, telemetry.get(k))

    persist_summary(session_id, st["summary"])
    await _yield_if_stopping(stop_ev, "summary.persisted", hard=True)

    budget_view = analyze_budget(
        llm=llm,
        messages=packed,
        requested_out_tokens=out_budget_adj,
        clamp_margin=int(eff["clamp_margin"]),
        reserved_system_tokens=int(eff.get("reserved_system_tokens") or 0),
    ).to_dict()
    await _yield_if_stopping(stop_ev, "budget.analyzed", hard=True)

    wb = _web_breakdown(telemetry.get("web", {}))
    telemetry.setdefault("web", {})["breakdown"] = wb
    telemetry["web"]["breakdown"]["unattributedWebSec"] = _web_unattributed(
        telemetry.get("web", {}), wb
    )
    telemetry["web"]["breakdown"]["prepSec"] = float(telemetry.get("prepSec") or 0.0)

    budget_view.setdefault("web", {}).update(telemetry.get("web", {}))
    budget_view.setdefault("rag", {}).update(telemetry.get("rag", {}))
    budget_view.setdefault("pack", {}).update(telemetry.get("pack", {}))

    out_budget, input_tokens_est = clamp_out_budget(
        llm=llm, messages=packed, requested_out=out_budget_adj, margin=int(eff["clamp_margin"])
    )
    await _yield_if_stopping(stop_ev, "budget.clamped", hard=True)

    budget_view.setdefault("request", {})
    budget_view["request"]["outBudgetRequested"] = out_budget_adj
    budget_view["request"]["temperature"] = temperature
    budget_view["request"]["top_p"] = top_p

    return Prep(
        llm=llm,
        session_id=session_id,
        packed=packed,
        st=st,
        out_budget=out_budget,
        input_tokens_est=input_tokens_est,
        budget_view=budget_view,
        temperature=temperature,
        top_p=top_p,
        t_request_start=t_request_start,
    )
