# aimodel/file_read/services/packing.py
from __future__ import annotations
from typing import Tuple, List, Dict, Optional
from ..core.memory import build_system, pack_messages, roll_summary_if_needed

def build_system_text() -> str:
    base = build_system(style="", short=False, bullets=False)
    guidance = (
        "\nYou may consult the prior messages to answer questions about the conversation itself "
        "(e.g., “what did I say first?”). When web context is present, consider it as evidence, "
        "prefer newer info if it conflicts with older memory, and respond in your own words."
    )
    return (base + guidance)

def pack_with_rollup(
    *, system_text: str, summary: str, recent, max_ctx: int, out_budget: int,
    ephemeral: Optional[List[Dict[str, str]]] = None,
) -> Tuple[List[Dict[str, str]], str, int]:
    packed, input_budget = pack_messages(
        style="", short=False, bullets=False,
        summary=summary, recent=recent, max_ctx=max_ctx, out_budget=out_budget
    )
    packed, new_summary = roll_summary_if_needed(
        packed=packed, recent=recent, summary=summary,
        input_budget=input_budget, system_text=system_text
    )

    # Inject ephemeral (web findings) BEFORE the last user message, so the final turn is still user.
    if ephemeral:
        last_user_idx = None
        for i in range(len(packed) - 1, -1, -1):
            m = packed[i]
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_idx = i
                break
        eph = list(ephemeral)
        if last_user_idx is not None:
            packed = packed[:last_user_idx] + eph + packed[last_user_idx:]
        else:
            packed = packed + eph

    return packed, new_summary, input_budget
