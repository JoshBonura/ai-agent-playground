from __future__ import annotations
from typing import List, Dict, Optional, Tuple
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
