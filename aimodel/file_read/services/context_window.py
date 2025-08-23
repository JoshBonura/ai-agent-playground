# aimodel/file_read/services/context_window.py
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from ..utils.streaming import safe_token_count_messages
from ..model_runtime import current_model_info

def estimate_tokens(llm, messages: List[Dict[str,str]]) -> Optional[int]:
    try:
        return safe_token_count_messages(llm, messages)
    except Exception:
        return None

def current_n_ctx() -> int:
    try:
        info = current_model_info() or {}
        cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
        return int(cfg.get("nCtx") or 4096)
    except Exception:
        return 4096

def clamp_out_budget(
    *, llm, messages: List[Dict[str,str]], requested_out: int, margin: int = 32
) -> Tuple[int, int]:
    inp_est = estimate_tokens(llm, messages)
    try:
        prompt_est = inp_est if inp_est is not None else safe_token_count_messages(llm, messages)
    except Exception:
        prompt_est = 1024
    n_ctx = current_n_ctx()
    available = max(16, n_ctx - prompt_est - margin)
    safe_out = max(16, min(requested_out, available))
    return safe_out, (inp_est if inp_est is not None else None)
