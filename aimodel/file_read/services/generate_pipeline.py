# aimodel/file_read/services/generate_pipeline.py
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from ..core.settings import SETTINGS
from ..runtime.model_runtime import ensure_ready, get_llm
from ..core.schemas import ChatBody
from .session_io import handle_incoming
from .packing import build_system_text, pack_with_rollup
from .prompt_utils import chars_len
from .router_text import compose_router_text
from .attachments import att_get
from ..web.router_ai import decide_web_and_fetch
from ..rag.retrieve_pipeline import build_rag_block_session_only_with_telemetry
from .generate_pipeline_support import (
    Prep,
    _bool,
    _approx_block_tokens,
)
from ..core.packing_memory_core import PACK_TELEMETRY
from .generate_pipeline_part2 import _finish_prepare_generation_with_telemetry

async def prepare_generation_with_telemetry(data: ChatBody) -> Prep:
    ensure_ready()
    llm = get_llm()
    t_request_start = time.perf_counter()
    eff0 = SETTINGS.effective()
    session_id = data.sessionId or eff0["default_session_id"]
    eff = SETTINGS.effective(session_id=session_id)

    rag_global_enabled = bool(eff.get("rag_global_enabled", True))
    rag_session_enabled = bool(eff.get("rag_session_enabled", True))
    force_session_only = bool(eff.get("rag_force_session_only")) or (not rag_global_enabled)

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
    print(f"[PIPE] incoming_msgs={len(incoming)}")
    latest_user = next((m for m in reversed(incoming) if m["role"] == "user"), {})
    latest_user_text = (latest_user.get("content") or "").strip()
    atts = (latest_user.get("attachments") or [])
    has_atts = bool(atts)
    print(f"[PIPE] latest_user_text_len={len(latest_user_text)} has_atts={has_atts} att_count={len(atts)}")

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

    telemetry: Dict[str, Any] = {"web": {}, "rag": {}, "pack": {}, "prepSec": round(time.perf_counter() - t_request_start, 6)}
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
                fb, fb_tel = await build_web_block(router_text, k=web_k)
                print(f"[PIPE][WEB] orchestrator block preview: {fb[:200]!r}" if fb else "[PIPE][WEB] orchestrator returned no block")
                print(f"[PIPE][WEB] orchestrator telemetry: {fb_tel}")
                if fb and fb.strip():
                    web_block = fb
                    injected_candidate = True
            except Exception as e:
                print(f"[PIPE][WEB] orchestrator fallback error: {e}")
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

            ephemeral_once.append({
                "role": "assistant",
                "content": web_text,
                "_ephemeral": True if ephemeral_only else False,
                "_source": "web"
            })

            telemetry["web"]["injectElapsedSec"] = round(time.perf_counter() - t0_inject, 6)
        else:
            telemetry["web"]["injected"] = False
            telemetry["web"]["injectElapsedSec"] = 0.0
    except Exception as e:
        print(f"[PIPE][WEB] error: {e}")
        telemetry["web"].setdefault("injected", False)
        telemetry["web"].setdefault("injectElapsedSec", 0.0)

    telemetry["web"]["ephemeralBlocks"] = len(ephemeral_once)
    print(f"[PIPE] has_atts={has_atts} disable_global_rag_on_attachments={bool(eff.get('disable_global_rag_on_attachments'))}")

    if has_atts and bool(eff.get("disable_global_rag_on_attachments")):
        att_names = [att_get(a, "name") for a in atts if att_get(a, "name")]
        query_for_atts = (base_user_text or "").strip() or " ".join(att_names) or "document"
        print(f"[PIPE] session-only RAG path query_for_atts={query_for_atts!r} att_names={att_names}")
        t0_att = time.perf_counter()
        try:
            att_block, att_tel = build_rag_block_session_only_with_telemetry(query_for_atts, session_id)
            print(f"[PIPE][RAG] session-only query: {query_for_atts!r}")
            print(f"[PIPE][RAG] session-only block preview: {att_block[:200]!r}" if att_block else "[PIPE][RAG] no session-only block")
        except Exception:
            att_block, att_tel = (None, {})
        if att_tel:
            telemetry["rag"].update(att_tel)
        print(f"[PIPE] session-only RAG built={bool(att_block)} block_chars={len(att_block or '')}")
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

    return await _finish_prepare_generation_with_telemetry(
        llm, eff, data, st, router_text, latest_user_text, base_user_text, has_atts,
        force_session_only, rag_session_enabled, rag_global_enabled, auto_rag,
        telemetry, packed, out_budget_req, temperature, top_p, t_request_start, session_id
    )
