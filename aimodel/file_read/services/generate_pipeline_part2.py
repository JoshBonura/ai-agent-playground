# aimodel/file_read/services/generate_pipeline_part2.py
from __future__ import annotations
import time
from typing import Any, Dict, Optional, List
from .prompt_utils import chars_len
from .generate_pipeline_support import (
    Prep, _tok_count, _approx_block_tokens, _diff_find_inserted_block,
    _web_breakdown, _web_unattributed, _enforce_fit
)
from ..rag.router_ai import decide_rag
from .packing import maybe_inject_rag_block
from .session_io import persist_summary
from .budget import analyze_budget
from ..core.packing_memory_core import PACK_TELEMETRY
from .context_window import clamp_out_budget

async def _finish_prepare_generation_with_telemetry(
    llm, eff, data, st, router_text, latest_user_text, base_user_text, has_atts,
    force_session_only, rag_session_enabled, rag_global_enabled, auto_rag,
    telemetry, packed, out_budget_req, temperature, top_p, t_request_start, session_id
) -> Prep:
    must_inject_session = bool(
        force_session_only and rag_session_enabled and not has_atts and not telemetry.get("web", {}).get("ephemeralBlocks")
    )

    rag_router_allowed = ((rag_session_enabled or rag_global_enabled) and not (
        has_atts and bool(eff["disable_global_rag_on_attachments"])
    )) or must_inject_session

    ephemeral_once: List[Dict[str, str]] = []
    if rag_router_allowed and bool(eff["rag_enabled"]) and not ephemeral_once:
        rag_need = False
        rag_query: Optional[str] = None

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
                try:
                    rag_need, rag_query = decide_rag(llm, router_text)
                except Exception:
                    rag_need, rag_query = (False, None)
            telemetry["rag"]["routerDecideSec"] = round(time.perf_counter() - t_router0, 6)
            telemetry["rag"]["routerNeeded"] = bool(rag_need)
            if rag_query is not None:
                telemetry["rag"]["routerQuery"] = rag_query

        skip_rag = bool(ephemeral_once) or (not rag_need)
        tokens_before = _tok_count(llm, packed)
        t_inject0 = time.perf_counter()

        print(f"[PIPE][RAG] router query: {rag_query!r} skip_rag={skip_rag}")
        res = maybe_inject_rag_block(
            packed,
            session_id=session_id,
            skip_rag=skip_rag,
            rag_query=rag_query,
            force_session_only=force_session_only,
        )

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
            print(f"[PIPE][RAG] injected block preview: {block_text[:200]!r}")
            telemetry["rag"]["blockChars"] = len(block_text)
            tok = _approx_block_tokens(llm, "user", block_text)
            if tok is not None:
                telemetry["rag"]["blockTokensApprox"] = tok
            telemetry["rag"]["injected"] = True
            telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or ("session-only" if force_session_only else "global")
        else:
            inserted = _diff_find_inserted_block(packed, packed2)
            if inserted and isinstance(inserted.get("content"), str):
                print(f"[PIPE][RAG] diff-inserted block preview: {inserted['content'][:200]!r}")
                text = inserted["content"]
                telemetry["rag"]["blockChars"] = len(text)
                tok = _approx_block_tokens(llm, "user", text)
                if tok is not None:
                    telemetry["rag"]["blockTokensApprox"] = tok
                telemetry["rag"]["injected"] = True
                telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or ("session-only" if force_session_only else "global")

        tokens_after = _tok_count(llm, packed2)
        if tokens_before is not None:
            telemetry["rag"]["packedTokensBefore"] = tokens_before
        if tokens_after is not None:
            telemetry["rag"]["packedTokensAfter"] = tokens_after
        if tokens_before is not None and tokens_after is not None:
            telemetry["rag"]["ragTokensAdded"] = max(0, tokens_after - tokens_before)
        packed = packed2
    else:
        telemetry["rag"]["routerSkipped"] = True
        if telemetry.get("web", {}).get("ephemeralBlocks"):
            telemetry["rag"]["routerSkippedReason"] = "ephemeral_block_present"
        elif not rag_router_allowed:
            telemetry["rag"]["routerSkippedReason"] = "attachments_disable_global_or_rag_disabled"
        elif not bool(eff["rag_enabled"]):
            telemetry["rag"]["routerSkippedReason"] = "rag_disabled"
        print(f"[PIPE] rag_router_skipped reason={telemetry['rag'].get('routerSkippedReason')}")

    packed, out_budget_adj = _enforce_fit(llm, eff, packed, out_budget_req)
    packed_chars = chars_len(packed)
    telemetry["pack"]["packedChars"] = packed_chars
    telemetry["pack"]["messages"] = len(packed)
    telemetry["pack"]["summarySec"] = float(PACK_TELEMETRY.get("summarySec") or 0.0)
    telemetry["pack"]["summaryTokensApprox"] = int(PACK_TELEMETRY.get("summaryTokensApprox") or 0)
    telemetry["pack"]["summaryUsedLLM"] = bool(PACK_TELEMETRY.get("summaryUsedLLM") or False)
    telemetry["pack"]["finalTrimSec"] = float(PACK_TELEMETRY.get("finalTrimSec") or 0.0)
    telemetry["pack"]["compressSec"] = float(PACK_TELEMETRY.get("compressSec") or 0.0)
    telemetry["pack"]["packInputTokensApprox"] = int(PACK_TELEMETRY.get("packInputTokensApprox") or 0)
    telemetry["pack"]["packMsgs"] = int(PACK_TELEMETRY.get("packMsgs") or 0)
    telemetry["pack"]["finalTrimTokensBefore"] = int(PACK_TELEMETRY.get("finalTrimTokensBefore") or 0)
    telemetry["pack"]["finalTrimTokensAfter"] = int(PACK_TELEMETRY.get("finalTrimTokensAfter") or 0)
    telemetry["pack"]["finalTrimDroppedMsgs"] = int(PACK_TELEMETRY.get("finalTrimDroppedMsgs") or 0)
    telemetry["pack"]["finalTrimDroppedApproxTokens"] = int(PACK_TELEMETRY.get("finalTrimDroppedApproxTokens") or 0)
    telemetry["pack"]["finalTrimSummaryShrunkFromChars"] = int(PACK_TELEMETRY.get("finalTrimSummaryShrunkFromChars") or 0)
    telemetry["pack"]["finalTrimSummaryShrunkToChars"] = int(PACK_TELEMETRY.get("finalTrimSummaryShrunkToChars") or 0)
    telemetry["pack"]["finalTrimSummaryDroppedChars"] = int(PACK_TELEMETRY.get("finalTrimSummaryDroppedChars") or 0)
    telemetry["pack"]["rollStartTokens"] = int(PACK_TELEMETRY.get("rollStartTokens") or 0)
    telemetry["pack"]["rollOverageTokens"] = int(PACK_TELEMETRY.get("rollOverageTokens") or 0)

    persist_summary(session_id, st["summary"])

    budget_view = analyze_budget(
        llm=llm,
        messages=packed,
        requested_out_tokens=out_budget_adj,
        clamp_margin=int(eff["clamp_margin"]),
        reserved_system_tokens=int(eff.get("reserved_system_tokens") or 0),
    ).to_dict()

    wb = _web_breakdown(telemetry.get("web", {}))
    telemetry.setdefault("web", {})["breakdown"] = wb
    telemetry["web"]["breakdown"]["unattributedWebSec"] = _web_unattributed(telemetry.get("web", {}), wb)
    telemetry["web"]["breakdown"]["prepSec"] = float(telemetry.get("prepSec") or 0.0)

    budget_view.setdefault("web", {}).update(telemetry.get("web", {}))
    budget_view.setdefault("rag", {}).update(telemetry.get("rag", {}))
    budget_view.setdefault("pack", {}).update(telemetry.get("pack", {}))

    out_budget, input_tokens_est = clamp_out_budget(
        llm=llm, messages=packed, requested_out=out_budget_adj, margin=int(eff["clamp_margin"])
    )
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
