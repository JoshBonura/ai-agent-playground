# aimodel/file_read/services/budget.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from .context_window import current_n_ctx, estimate_tokens

@dataclass
class TurnBudget:
    n_ctx: int
    input_tokens_est: Optional[int]
    requested_out_tokens: int
    clamped_out_tokens: int
    clamp_margin: int
    reserved_system_tokens: Optional[int] = None
    available_for_out_tokens: Optional[int] = None
    headroom_tokens: Optional[int] = None
    overage_tokens: Optional[int] = None
    reason: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def analyze_budget(
    llm: Any,
    messages: List[Dict[str, str]],
    *,
    requested_out_tokens: int,
    clamp_margin: int,
    reserved_system_tokens: Optional[int] = None,
) -> TurnBudget:
    n_ctx = current_n_ctx()
    try:
        inp = estimate_tokens(llm, messages)
    except Exception:
        inp = None

    rst = int(reserved_system_tokens or 0)
    min_out = 16

    if inp is None:
        available = None
        clamped = requested_out_tokens
        headroom = None
        overage = None
        reason = "input_tokens_unknown"
    else:
        available_raw = n_ctx - inp - clamp_margin - rst
        available = max(min_out, available_raw)
        clamped = max(min_out, min(requested_out_tokens, available))
        headroom = max(0, available - clamped)
        overage = max(0, requested_out_tokens - available)
        reason = "ok" if overage == 0 else "requested_exceeds_available"

    return TurnBudget(
        n_ctx=n_ctx,
        input_tokens_est=inp,
        requested_out_tokens=requested_out_tokens,
        clamped_out_tokens=clamped,
        clamp_margin=clamp_margin,
        reserved_system_tokens=reserved_system_tokens,
        available_for_out_tokens=available,
        headroom_tokens=headroom,
        overage_tokens=overage,
        reason=reason,
    )
