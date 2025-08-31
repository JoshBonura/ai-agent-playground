# aimodel/file_read/services/generate_pipeline.py
# main generate pipeline orchestrator; no inline comments per request
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from ..core.settings import SETTINGS
from ..runtime.model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody
from .session_io import handle_incoming, persist_summary
from .packing import build_system_text, pack_with_rollup, maybe_inject_rag_block
from .prompt_utils import chars_len
from .router_text import compose_router_text
from .attachments import att_get
from .budget import analyze_budget
from .context_window import clamp_out_budget
from ..web.router_ai import decide_web_and_fetch
from ..rag.router_ai import decide_rag
from ..rag.retrieve import build_rag_block_session_only
from ..core.packing_memory_core import PACK_TELEMETRY, SUMMARY_TEL
from .generate_pipeline_support import (
    Prep,
    _bool,
    _tok_count,
    _approx_block_tokens,
    _diff_find_inserted_block,
    _web_breakdown,
    _web_unattributed,
    _enforce_fit,
)

async def prepare_generation_with_telemetry(data: ChatBody) -> Prep:
    ensure_ready()
    llm = get_llm()
    t_request_start = time.perf_counter()
    eff0 = SETTINGS.effective()
    session_id = data.sessionId or eff0["default_session_id"]
    eff = SETTINGS.effective(session_id=session_id)
    temperature = float(eff["default_temperature"] if getattr(data, "temperature") is None else data.temperature)
    top_p = float(eff["default_top_p"] if getattr(data, "top_p") is None else data.top_p)
    out_budget_req = int(eff["default_max_tokens"] if getattr(data, "max_tokens") is None else data.max_tokens)
    auto_web = _bool(eff["default_auto_web"])
    if getattr(data, "autoWeb") is not None:
        auto_web = _bool(data.autoWeb)
    web_k = int(eff["default_web_k"] if getattr(data, "webK") is None else data.webK)
    web_k = max(int(eff["web_k_min"]), min(web_k, int(eff["web_k_max"])))
    auto_rag = _bool(eff["default_auto_rag"])
    if getattr(data, "autoRag") is not None:
        auto_rag = _bool(data.autoRag)
    model_ctx = int(eff["model_ctx"])
    incoming = [
        {
            "role": m.role,
            "content": m.content,
            "attachments": getattr(m, "attachments", None),
        }
        for m in (data.messages or [])
    ]
    latest_user = next((m for m in reversed(incoming) if m["role"] == "user"), {})
    latest_user_text = (latest_user.get("content") or "").strip()
    atts = (latest_user.get("attachments") or [])
    has_atts = bool(atts)
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
    telemetry: Dict[str, Any] = {"web": {}, "rag": {}, "pack": {}}
    ephemeral_once: List[Dict[str, str]] = []
    telemetry["web"]["injectElapsedSec"] = 0.0
    telemetry["web"]["ephemeralBlocks"] = 0
    try:
        web_block: Optional[str] = None
        web_tel: Dict[str, Any] = {}
        if auto_web and not (has_atts and bool(eff.get("disable_global_rag_on_attachments"))):
            res = await decide_web_and_fetch(llm, router_text, k=web_k)
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
        if (need_flag is True) and (not injected_candidate):
            try:
                from ..web.orchestrator import build_web_block
                fb = await build_web_block(router_text, k=web_k)
                if fb and fb.strip():
                    web_block = fb
                    injected_candidate = True
            except Exception:
                pass
        if injected_candidate:
            t0_inject = time.perf_counter()
            web_text = str(eff["web_block_preamble"]) + "\n\n" + web_block.strip()
            telemetry["web"]["blockChars"] = len(web_text)
            tok = _approx_block_tokens(llm, "assistant", web_text)
            if tok is not None:
                telemetry["web"]["blockTokensApprox"] = tok
            telemetry["web"]["injected"] = True
            ephemeral_once.append({"role": "assistant", "content": web_text, "_ephemeral": True})
            telemetry["web"]["injectElapsedSec"] = round(time.perf_counter() - t0_inject, 6)
        else:
            telemetry["web"]["injected"] = False
            telemetry["web"]["injectElapsedSec"] = 0.0
    except Exception:
        telemetry["web"].setdefault("injected", False)
        telemetry["web"].setdefault("injectElapsedSec", 0.0)
    telemetry["web"]["ephemeralBlocks"] = len(ephemeral_once)
    if has_atts and bool(eff.get("disable_global_rag_on_attachments")):
        att_names = [att_get(a, "name") for a in atts if att_get(a, "name")]
        query_for_atts = (base_user_text or "").strip() or " ".join(att_names) or "document"
        t0_att = time.perf_counter()
        try:
            att_block = build_rag_block_session_only(query_for_atts, session_id)
        except Exception:
            att_block = None
        if att_block:
            rag_text = str(eff["rag_block_preamble"]) + "\n\n" + att_block
            telemetry["rag"]["sessionOnly"] = True
            telemetry["rag"]["mode"] = "session-only"
            telemetry["rag"]["blockChars"] = len(rag_text)
            tok = _approx_block_tokens(llm, "assistant", rag_text)
            if tok is not None:
                telemetry["rag"]["sessionOnlyTokensApprox"] = tok
            telemetry["rag"]["injected"] = True
            ephemeral_once.append({"role": "assistant", "content": rag_text, "_ephemeral": True})
        else:
            telemetry["rag"]["sessionOnly"] = False
            telemetry["rag"].setdefault("injected", False)
        telemetry["rag"]["sessionOnlyBuildSec"] = round(time.perf_counter() - t0_att, 6)
    system_text = build_system_text()
    t_pack0 = time.perf_counter()
    packed, st["summary"], _ = pack_with_rollup(
        system_text=system_text,
        summary=st["summary"],
        recent=st["recent"],
        max_ctx=model_ctx,
        out_budget=out_budget_req,
        ephemeral=ephemeral_once,
    )
    telemetry["pack"]["packSec"] = round(time.perf_counter() - t_pack0, 6)
    rag_router_allowed = not (has_atts and bool(eff.get("disable_global_rag_on_attachments")))
    if rag_router_allowed and bool(eff.get("rag_enabled", True)) and not ephemeral_once:
        rag_need = False
        rag_query: Optional[str] = None
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
        res = maybe_inject_rag_block(
            packed,
            session_id=session_id,
            skip_rag=skip_rag,
            rag_query=rag_query,
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
            telemetry["rag"]["blockChars"] = len(block_text)
            tok = _approx_block_tokens(llm, "user", block_text)
            if tok is not None:
                telemetry["rag"]["blockTokensApprox"] = tok
            telemetry["rag"]["injected"] = True
            telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or "global"
        else:
            inserted = _diff_find_inserted_block(packed, packed2)
            if inserted and isinstance(inserted.get("content"), str):
                text = inserted["content"]
                telemetry["rag"]["blockChars"] = len(text)
                tok = _approx_block_tokens(llm, "user", text)
                if tok is not None:
                    telemetry["rag"]["blockTokensApprox"] = tok
                telemetry["rag"]["injected"] = True
                telemetry["rag"]["mode"] = telemetry["rag"].get("mode") or "global"
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
        if ephemeral_once:
            telemetry["rag"]["routerSkippedReason"] = "ephemeral_block_present"
        elif not rag_router_allowed:
            telemetry["rag"]["routerSkippedReason"] = "attachments_disable_global"
        elif not bool(eff.get("rag_enabled", True)):
            telemetry["rag"]["routerSkippedReason"] = "rag_disabled"
    packed, out_budget_adj = _enforce_fit(llm, eff, packed, out_budget_req)
    packed_chars = chars_len(packed)
    telemetry["pack"]["packedChars"] = packed_chars
    telemetry["pack"]["messages"] = len(packed)
    telemetry["pack"]["summarySec"] = float(PACK_TELEMETRY.get("summarySec") or 0.0)
    telemetry["pack"]["summaryTokensApprox"] = int(PACK_TELEMETRY.get("summaryTokensApprox") or 0)
    telemetry["pack"]["summaryUsedLLM"] = bool(PACK_TELEMETRY.get("summaryUsedLLM") or False)
    telemetry["pack"]["finalTrimSec"] = float(PACK_TELEMETRY.get("finalTrimSec") or 0.0)
    telemetry["pack"]["compressSec"] = float(PACK_TELEMETRY.get("compressSec") or 0.0)
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
