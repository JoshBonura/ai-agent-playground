from __future__ import annotations
import time
from typing import Dict, List

from .packing_memory_core import (
    _SETTINGS,
    count_prompt_tokens,
    approx_tokens,
    summarize_chunks,
    _compress_summary_block,
    PACK_TELEMETRY,
)
from .style import get_style_sys

def build_system(style: str, short: bool, bullets: bool) -> str:
    cfg = _SETTINGS.get()
    base = get_style_sys()
    parts = [base]
    if style and style != base:
        parts.append(style)
    if short:
        parts.append(cfg["system_brief_directive"])
    if bullets:
        parts.append(cfg["system_bullets_directive"])
    parts.append(cfg["system_follow_user_style_directive"])
    return " ".join(parts)

def pack_messages(style: str, short: bool, bullets: bool, summary, recent, max_ctx, out_budget):
    t0_pack = time.time()
    cfg = _SETTINGS.get()
    model_ctx = int(max_ctx or cfg["model_ctx"])
    gen_budget = int(out_budget or cfg["out_budget"])
    reserved = int(cfg["reserved_system_tokens"])
    input_budget = model_ctx - gen_budget - reserved
    if input_budget < int(cfg["min_input_budget"]):
        input_budget = int(cfg["min_input_budget"])
    sys_text = build_system(style, short, bullets)
    prologue = [{"role": "user", "content": sys_text}]
    if summary:
        prologue.append({"role": "user", "content": cfg["summary_header_prefix"] + summary})
    packed = prologue + list(recent)
    try:
        PACK_TELEMETRY["packInputTokensApprox"] = int(count_prompt_tokens(packed))
        PACK_TELEMETRY["packMsgs"] = int(len(packed))
    except Exception:
        pass
    PACK_TELEMETRY["packSec"] += float(time.time() - t0_pack)
    return packed, input_budget

def _final_safety_trim(packed: List[Dict[str,str]], input_budget: int) -> List[Dict[str,str]]:
    t0 = time.time()
    cfg = _SETTINGS.get()
    keep_ratio = float(cfg["final_shrink_summary_keep_ratio"])
    min_keep = int(cfg["final_shrink_summary_min_chars"])
    def toks() -> int:
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999999
    t_before = toks()
    PACK_TELEMETRY["finalTrimTokensBefore"] = int(t_before)
    dropped_msgs = 0
    dropped_tokens = 0
    keep_head = 2 if len(packed) >= 2 and isinstance(packed[1].get("content"), str) and packed[1]["content"].startswith(cfg["summary_header_prefix"]) else 1
    while toks() > input_budget and len(packed) > keep_head + 1:
        dropped = packed.pop(keep_head)
        try:
            dropped_tokens += int(approx_tokens(dropped["content"]))
            dropped_msgs += 1
        except Exception:
            pass
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        summary_msg = packed[1]
        txt = summary_msg["content"]
        n = max(min_keep, int(len(txt) * keep_ratio))
        try:
            PACK_TELEMETRY["finalTrimSummaryShrunkFromChars"] = int(len(txt))
        except Exception:
            pass
        summary_msg["content"] = txt[-n:]
        try:
            PACK_TELEMETRY["finalTrimSummaryShrunkToChars"] = int(len(summary_msg["content"]))
            PACK_TELEMETRY["finalTrimSummaryDroppedChars"] = int(max(0, int(PACK_TELEMETRY["finalTrimSummaryShrunkFromChars"]) - int(PACK_TELEMETRY["finalTrimSummaryShrunkToChars"])))
        except Exception:
            pass
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        removed = packed.pop(1)
        try:
            dropped_tokens += int(approx_tokens(removed["content"]))
            dropped_msgs += 1
        except Exception:
            pass
    while toks() > input_budget and len(packed) > 2:
        removed = packed.pop(2 if len(packed) > 3 else 1)
        try:
            dropped_tokens += int(approx_tokens(removed["content"]))
            dropped_msgs += 1
        except Exception:
            pass
    t_after = toks()
    PACK_TELEMETRY["finalTrimTokensAfter"] = int(t_after)
    PACK_TELEMETRY["finalTrimDroppedMsgs"] = int(dropped_msgs)
    PACK_TELEMETRY["finalTrimDroppedApproxTokens"] = int(max(0, dropped_tokens))
    PACK_TELEMETRY["finalTrimSec"] += float(time.time() - t0)
    return packed

def roll_summary_if_needed(packed, recent, summary, input_budget, system_text):
    cfg = _SETTINGS.get()
    def _tok():
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999999
    start_tokens = _tok()
    overage = start_tokens - input_budget
    PACK_TELEMETRY["rollStartTokens"] = int(start_tokens)
    PACK_TELEMETRY["rollOverageTokens"] = int(overage)
    if overage <= int(cfg["skip_overage_lt"]):
        packed = _final_safety_trim(packed, input_budget)
        PACK_TELEMETRY["rollEndTokens"] = int(count_prompt_tokens(packed))
        return packed, summary
    peels_done = 0
    peeled_n = 0
    if len(recent) > 6 and peels_done < int(cfg["max_peel_per_turn"]):
        peel_min = int(cfg["peel_min"])
        peel_frac = float(cfg["peel_frac"])
        peel_max = int(cfg["peel_max"])
        target = max(peel_min, min(peel_max, int(len(recent) * peel_frac)))
        peel = []
        for _ in range(min(target, len(recent))):
            peel.append(recent.popleft())
        peeled_n = len(peel)
        t0_sum = time.time()
        new_sum, _used_llm = summarize_chunks(peel)
        PACK_TELEMETRY["summarySec"] += float(time.time() - t0_sum)
        if new_sum.startswith(cfg["bullet_prefix"]):
            summary = (summary + "\n" + new_sum).strip() if summary else new_sum
        else:
            summary = new_sum
        t0_comp = time.time()
        summary = _compress_summary_block(summary)
        PACK_TELEMETRY["compressSec"] += float(time.time() - t0_comp)
        try:
            PACK_TELEMETRY["rollPeeledMsgs"] = int(peeled_n)
            PACK_TELEMETRY["rollNewSummaryChars"] = int(len(summary))
            PACK_TELEMETRY["rollNewSummaryTokensApprox"] = int(approx_tokens(summary))
        except Exception:
            pass
        packed = [
            {"role": "user", "content": system_text},
            {"role": "user", "content": cfg["summary_header_prefix"] + summary},
            *list(recent),
        ]
    t0_trim = time.time()
    packed = _final_safety_trim(packed, input_budget)
    PACK_TELEMETRY["finalTrimSec"] += float(time.time() - t0_trim)
    end_tokens = count_prompt_tokens(packed)
    PACK_TELEMETRY["rollEndTokens"] = int(end_tokens)
    return packed, summary
