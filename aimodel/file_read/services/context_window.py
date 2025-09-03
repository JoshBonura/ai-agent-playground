# aimodel/file_read/services/context_window.py
from __future__ import annotations
from typing import List, Dict, Optional, Tuple, Any
from ..utils.streaming import safe_token_count_messages
from ..runtime.model_runtime import current_model_info
from ..core.settings import SETTINGS

def estimate_tokens(llm, messages: List[Dict[str, str]]) -> Optional[int]:
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
    *, llm, messages: List[Dict[str, str]], requested_out: int, margin: int = 32, reserved_system_tokens: Optional[int] = None
) -> Tuple[int, Optional[int]]:
    eff = SETTINGS.effective()
    inp_est = estimate_tokens(llm, messages)
    try:
        prompt_est = inp_est if inp_est is not None else safe_token_count_messages(llm, messages)
    except Exception:
        prompt_est = int(eff["token_estimate_fallback"])
    n_ctx = current_n_ctx()
    rst = int(reserved_system_tokens or 0)
    min_out = int(eff.get("min_out_tokens", 16))
    available = max(min_out, n_ctx - prompt_est - margin - rst)
    safe_out = max(min_out, min(requested_out, available))
    return safe_out, (inp_est if inp_est is not None else None)

def compute_budget_view(
    llm,
    messages: List[Dict[str, str]],
    requested_out: Optional[int] = None,
    clamp_margin: Optional[int] = None,
    reserved_system_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    eff = SETTINGS.effective()
    n_ctx = current_n_ctx()
    margin = int(clamp_margin if clamp_margin is not None else eff.get("clamp_margin", 32))
    rst = int(reserved_system_tokens if reserved_system_tokens is not None else eff.get("reserved_system_tokens", 0))
    min_out = int(eff.get("min_out_tokens", 16))
    default_out = int(eff.get("out_budget", 512))
    req_out = int(requested_out if requested_out is not None else default_out)

    inp_opt = estimate_tokens(llm, messages)
    if inp_opt is None:
        try:
            prompt_est = safe_token_count_messages(llm, messages)
        except Exception:
            prompt_est = int(eff["token_estimate_fallback"])
    else:
        prompt_est = int(inp_opt)

    available = max(min_out, n_ctx - prompt_est - margin - rst)
    out_budget_chosen = max(min_out, min(req_out, available))
    over_by_tokens = max(0, (prompt_est + req_out + margin + rst) - n_ctx)
    usable_ctx = max(0, n_ctx - margin - rst)

    return {
        "modelCtx": n_ctx,
        "clampMargin": margin,
        "usableCtx": usable_ctx,
        "reservedSystemTokens": rst,
        "inputTokensEst": prompt_est,
        "outBudgetChosen": out_budget_chosen,
        "outBudgetDefault": default_out,
        "outBudgetRequested": req_out,
        "outBudgetMaxAllowed": available,
        "overByTokens": over_by_tokens,
        "minOutTokens": min_out,
        "queueWaitSec": None,
    }
