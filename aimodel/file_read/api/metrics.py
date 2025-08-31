# aimodel/file_read/api/metrics.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ..runtime.model_runtime import get_llm
from ..services.packing import build_system_text, pack_with_rollup
from ..services.budget import analyze_budget
from ..core.settings import SETTINGS
from ..store import list_messages, get_summary, set_summary

router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("/budget")
def get_budget(sessionId: Optional[str] = Query(default=None), maxTokens: Optional[int] = None):
    eff0 = SETTINGS.effective()
    sid = sessionId or eff0["default_session_id"]
    llm = get_llm()
    eff = SETTINGS.effective(session_id=sid)

    # Rebuild the packed prompt (no streaming)
    msgs = [{"role": m.role, "content": m.content} for m in list_messages(sid)]
    summary = get_summary(sid)
    system_text = build_system_text()
    packed, new_summary, _ = pack_with_rollup(
        system_text=system_text,
        summary=summary,
        recent=msgs,
        max_ctx=int(eff["model_ctx"]),
        out_budget=int(eff["default_max_tokens"]),
    )
    if new_summary != summary:
        set_summary(sid, new_summary)

    requested_out = int(maxTokens or eff["default_max_tokens"])
    budget = analyze_budget(
        llm=llm,
        messages=packed,
        requested_out_tokens=requested_out,
        clamp_margin=int(eff["clamp_margin"]),
        reserved_system_tokens=int(eff.get("reserved_system_tokens") or 0),
    ).to_dict()
    return {"sessionId": sid, "budget": budget}
