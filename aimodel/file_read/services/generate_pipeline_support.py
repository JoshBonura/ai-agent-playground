# aimodel/file_read/services/generate_pipeline_support.py
# utility helpers for generate pipeline; no inline comments per request
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from ..utils.streaming import safe_token_count_messages

@dataclass
class Prep:
    llm: Any
    session_id: str
    packed: List[Dict[str, str]]
    st: Dict[str, Any]
    out_budget: int
    input_tokens_est: Optional[int]
    budget_view: Dict[str, Any]
    temperature: float
    top_p: float
    t_request_start: float

def _bool(v, default: bool = False) -> bool:
    try:
        return bool(v)
    except Exception:
        return bool(default)

def _tok_count(llm, messages: List[Dict[str, str]]) -> Optional[int]:
    try:
        return int(safe_token_count_messages(llm, messages))
    except Exception:
        return None

def _approx_block_tokens(llm, role: str, text: str) -> Optional[int]:
    return _tok_count(llm, [{"role": role, "content": text}])

def _diff_find_inserted_block(before: List[Dict[str, str]], after: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if len(after) - len(before) != 1:
        return None
    i = 0
    while i < len(before) and before[i] == after[i]:
        i += 1
    if i < len(after):
        return after[i]
    return None

def _dump_msgs(label: str, msgs: List[Dict[str, str]], head_chars: int = 180):
    return

def _web_breakdown(web: Dict[str, Any]) -> Dict[str, float]:
    w = web or {}
    orch = w.get("orchestrator") or {}
    router = float(w.get("elapsedSec") or 0.0)
    summarize = float((w.get("summarizer") or {}).get("elapsedSec") or 0.0)
    inject = float(w.get("injectElapsedSec") or 0.0)
    search_total = 0.0
    s1 = (orch.get("search") or {})
    for k in ("elapsedSecTotal", "elapsedSec"):
        if isinstance(s1.get(k), (int, float)):
            search_total = float(s1[k])
            break
    fetch1 = float((orch.get("fetch1") or {}).get("totalSec") or 0.0)
    fetch2 = float((orch.get("fetch2") or {}).get("totalSec") or 0.0)
    orch_elapsed = float(orch.get("elapsedSec") or w.get("fetchElapsedSec") or 0.0)
    assemble = orch_elapsed - (search_total + fetch1 + fetch2)
    if assemble < 0:
        assemble = 0.0
    total_pre_ttft = router + summarize + orch_elapsed + inject
    return {
        "routerSec": round(router, 6),
        "summarizeSec": round(summarize, 6),
        "searchSec": round(search_total, 6),
        "fetchSec": round(fetch1, 6),
        "jsFetchSec": round(fetch2, 6),
        "assembleSec": round(assemble, 6),
        "orchestratorSec": round(orch_elapsed, 6),
        "injectSec": round(inject, 6),
        "totalWebPreTtftSec": round(total_pre_ttft, 6),
    }

def _web_unattributed(web: Dict[str, Any], breakdown: Dict[str, float]) -> float:
    total = float((web or {}).get("fetchElapsedSec") or 0.0)
    explained = float(breakdown.get("searchSec", 0.0)) + float(breakdown.get("fetchSec", 0.0)) + float(breakdown.get("jsFetchSec", 0.0)) + float(breakdown.get("assembleSec", 0.0))
    ua = total - explained
    return round(ua if ua > 0 else 0.0, 6)

def _enforce_fit(llm, eff: Dict[str, Any], packed: List[Dict[str, str]], out_budget_req: int) -> tuple[list[dict], int]:
    tok = _tok_count(llm, packed) or 0
    capacity = int(eff["model_ctx"]) - int(eff["clamp_margin"])
    def drop_one(px):
        keep_head = 2 if len(px) >= 2 and isinstance(px[1].get("content"), str) and px[1]["content"].startswith(eff["summary_header_prefix"]) else 1
        if len(px) > keep_head + 1:
            px.pop(keep_head)
            return True
        return False
    def remove_ephemeral_blocks(px):
        i = 0
        removed = False
        while i < len(px):
            m = px[i]
            if m.get("_ephemeral") is True:
                px.pop(i)
                removed = True
            else:
                i += 1
        return removed
    if tok + out_budget_req > capacity:
        if remove_ephemeral_blocks(packed):
            tok = _tok_count(llm, packed) or 0
    while tok + out_budget_req > capacity and drop_one(packed):
        tok = _tok_count(llm, packed) or 0
    if tok >= capacity:
        ob2 = 0
    else:
        ob2 = min(out_budget_req, max(0, capacity - tok))
    return packed, ob2
