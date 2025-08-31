from __future__ import annotations
import time
from typing import Dict, List

from .packing_memory_core import (
    _SETTINGS,
    _log,
    count_prompt_tokens,
    approx_tokens,
    summarize_chunks,
    _compress_summary_block,
    PACK_TELEMETRY,
)
from .style import STYLE_SYS

def build_system(style: str, short: bool, bullets: bool) -> str:
    cfg = _SETTINGS.get()
    _log(f"build_system flags short={short} bullets={bullets}")
    parts = [STYLE_SYS]
    if style and style != STYLE_SYS:
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
    _log(f"pack_messages SETTINGS snapshot: {model_ctx=}, {gen_budget=}, {input_budget=}")
    _log(f"pack_messages OUT msgs={len(packed)} tokens~{count_prompt_tokens(packed)} (model_ctx={model_ctx}, out_budget={gen_budget}, input_budget={input_budget})")
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
    _log(f"final_trim START tokens={toks()} budget={input_budget}")
    keep_head = 2 if len(packed) >= 2 and isinstance(packed[1].get("content"), str) and packed[1]["content"].startswith(cfg["summary_header_prefix"]) else 1
    while toks() > input_budget and len(packed) > keep_head + 1:
        dropped = packed.pop(keep_head)
        _log(f"final_trim DROP msg role={dropped['role']} size~{approx_tokens(dropped['content'])} toks={toks()}")
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        summary_msg = packed[1]
        txt = summary_msg["content"]
        n = max(min_keep, int(len(txt) * keep_ratio))
        summary_msg["content"] = txt[-n:]
        _log(f"final_trim SHRINK summary to {len(summary_msg['content'])} chars toks={toks()}")
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        removed = packed.pop(1)
        _log(f"final_trim REMOVE summary len~{len(removed['content'])} toks={toks()}")
    while toks() > input_budget and len(packed) > 2:
        removed = packed.pop(2 if len(packed) > 3 else 1)
        _log(f"final_trim LAST_RESORT drop size~{approx_tokens(removed['content'])} toks={toks()}")
    _log(f"final_trim END tokens={toks()} msgs={len(packed)}")
    PACK_TELEMETRY["finalTrimSec"] += float(time.time() - t0)
    return packed

def roll_summary_if_needed(packed, recent, summary, input_budget, system_text):
    cfg = _SETTINGS.get()
    _log("=== roll_summary_if_needed DEBUG START ===")
    _log(f"skip_overage_lt={cfg['skip_overage_lt']}, max_peel_per_turn={cfg['max_peel_per_turn']}, peel_min={cfg['peel_min']}, peel_frac={cfg['peel_frac']}, peel_max={cfg['peel_max']}")
    _log(f"len(recent)={len(recent)}, current_summary_len={len(summary) if summary else 0}")
    _log(f"input_budget={input_budget}, reserved_system_tokens={cfg['reserved_system_tokens']}")
    _log(f"model_ctx={cfg['model_ctx']}, out_budget={cfg['out_budget']}")
    def _tok():
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999999
    start_tokens = _tok()
    overage = start_tokens - input_budget
    _log(f"roll_summary_if_needed START tokens={start_tokens} input_budget={input_budget} overage={overage}")
    if overage <= int(cfg["skip_overage_lt"]):
        _log(f"roll_summary_if_needed SKIP (overage {overage} <= {cfg['skip_overage_lt']})")
        packed = _final_safety_trim(packed, input_budget)
        return packed, summary
    peels_done = 0
    if len(recent) > 6 and peels_done < int(cfg["max_peel_per_turn"]):
        peel_min = int(cfg["peel_min"])
        peel_frac = float(cfg["peel_frac"])
        peel_max = int(cfg["peel_max"])
        target = max(peel_min, min(peel_max, int(len(recent) * peel_frac)))
        peel = []
        for _ in range(min(target, len(recent))):
            peel.append(recent.popleft())
        _log(f"roll_summary peeled={len(peel)}")
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
        packed = [
            {"role": "user", "content": system_text},
            {"role": "user", "content": cfg["summary_header_prefix"] + summary},
            *list(recent),
        ]
        _log(f"roll_summary updated summary_len={len(summary)} tokens={_tok()}")
    t0_trim = time.time()
    packed = _final_safety_trim(packed, input_budget)
    PACK_TELEMETRY["finalTrimSec"] += float(time.time() - t0_trim)
    _log(f"roll_summary_if_needed END tokens={count_prompt_tokens(packed)}")
    _log("=== roll_summary_if_needed DEBUG END ===")
    return packed, summary
