from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Any
from ..utils.streaming import safe_token_count_messages
from ..runtime.model_runtime import current_model_info
from ..core.settings import SETTINGS

def estimate_tokens(llm, messages: List[Dict[str,str]]) -> Optional[int]:
    try:
        return safe_token_count_messages(llm, messages)
    except Exception:
        return None

def current_n_ctx() -> int:
    eff = SETTINGS.effective()
    try:
        info = current_model_info() or {}
        cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
        return int(cfg.get("nCtx") or eff["nctx_fallback"])
    except Exception:
        return int(eff["nctx_fallback"])

def clamp_out_budget(
    *, llm, messages: List[Dict[str,str]], requested_out: int, margin: int = 32
) -> Tuple[int, int]:
    eff = SETTINGS.effective()
    inp_est = estimate_tokens(llm, messages)
    try:
        prompt_est = inp_est if inp_est is not None else safe_token_count_messages(llm, messages)
    except Exception:
        prompt_est = int(eff["token_estimate_fallback"])
    n_ctx = current_n_ctx()
    available = max(int(eff["min_out_tokens"]), n_ctx - prompt_est - margin)
    safe_out = max(int(eff["min_out_tokens"]), min(requested_out, available))
    return safe_out, (inp_est if inp_est is not None else None)

def compute_budget_view(
    llm,
    messages: List[Dict[str, str]],
    requested_out: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Returns a structured snapshot of the token budget for this request.
    Uses your existing safe_token_count + nCtx logic to stay consistent
    with clamp_out_budget().
    """
    eff = SETTINGS.effective()
    n_ctx = current_n_ctx()
    margin = int(eff.get("clamp_margin", 32))
    min_out = int(eff.get("min_out_tokens", 16))
    default_out = int(eff.get("out_budget", 512))
    req_out = int(requested_out or default_out)

    # input estimate (with fallback identical to clamp_out_budget)
    inp_opt = estimate_tokens(llm, messages)
    if inp_opt is None:
        try:
            from ..utils.streaming import safe_token_count_messages
            prompt_est = safe_token_count_messages(llm, messages)
        except Exception:
            prompt_est = int(eff["token_estimate_fallback"])
    else:
        prompt_est = int(inp_opt)

    # capacity available for output per current policy (same formula as clamp_out_budget)
    available = max(min_out, n_ctx - prompt_est - margin)

    # chosen output budget (respect requested/default but never exceed available)
    out_budget_chosen = max(min_out, min(req_out, available))

    # diagnostics
    over_by_tokens = max(0, (prompt_est + req_out + margin) - n_ctx)
    usable_ctx = max(0, n_ctx - margin)

    return {
        # model/window
        "modelCtx": n_ctx,
        "clampMargin": margin,
        "usableCtx": usable_ctx,

        # input side
        "inputTokensEst": prompt_est,

        # output side
        "outBudgetChosen": out_budget_chosen,
        "outBudgetDefault": default_out,
        "outBudgetRequested": req_out,
        "outBudgetMaxAllowed": max(min_out, available),

        # heads-up flags
        "overByTokens": over_by_tokens,   # >0 means request (req_out) would overflow if granted
        "minOutTokens": min_out,

        # timing slot (filled by caller/streaming_worker if they measure queue wait)
        "queueWaitSec": None,
    }