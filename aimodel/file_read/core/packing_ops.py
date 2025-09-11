from __future__ import annotations

import time

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from .packing_memory_core import (PACK_TELEMETRY, _compress_summary_block,
                                  approx_tokens, count_prompt_tokens,
                                  summarize_chunks)
from .style import get_style_sys

log = get_logger(__name__)


def _S() -> dict:
    """Effective settings snapshot."""
    return SETTINGS.effective()


def build_system(style: str, short: bool, bullets: bool) -> str:
    cfg = _S()
    base = get_style_sys()

    parts: list[str] = [base]
    if style and style != base:
        parts.append(style)

    if short:
        parts.append(cfg.get("system_brief_directive", ""))

    if bullets:
        parts.append(cfg.get("system_bullets_directive", ""))

    follow = cfg.get("system_follow_user_style_directive", "")
    if follow:
        parts.append(follow)

    # Avoid stray spaces if some directives are blank
    return " ".join(p for p in parts if p)


def pack_messages(style: str, short: bool, bullets: bool, summary, recent, max_ctx, out_budget):
    t0_pack = time.time()
    cfg = _S()

    model_ctx = int(max_ctx or cfg.get("model_ctx", 8192))
    gen_budget = int(out_budget or cfg.get("out_budget", 1024))
    reserved = int(cfg.get("reserved_system_tokens", 256))
    min_input_budget = int(cfg.get("min_input_budget", 512))

    input_budget = model_ctx - gen_budget - reserved
    if input_budget < min_input_budget:
        input_budget = min_input_budget

    sys_text = build_system(style, short, bullets)
    prologue = [{"role": "user", "content": sys_text}]

    summary_header_prefix = cfg.get("summary_header_prefix", "## Summary\n")
    if summary:
        prologue.append({"role": "user", "content": summary_header_prefix + summary})

    packed = prologue + list(recent)

    try:
        PACK_TELEMETRY["packInputTokensApprox"] = int(count_prompt_tokens(packed))
        PACK_TELEMETRY["packMsgs"] = len(packed)
    except Exception:
        pass

    PACK_TELEMETRY["packSec"] += float(time.time() - t0_pack)
    return packed, input_budget


def _final_safety_trim(packed: list[dict[str, str]], input_budget: int) -> list[dict[str, str]]:
    t0 = time.time()
    cfg = _S()

    keep_ratio = float(cfg.get("final_shrink_summary_keep_ratio", 0.5))
    min_keep = int(cfg.get("final_shrink_summary_min_chars", 200))
    summary_header_prefix = cfg.get("summary_header_prefix", "## Summary")

    def toks() -> int:
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999_999

    t_before = toks()
    PACK_TELEMETRY["finalTrimTokensBefore"] = int(t_before)

    dropped_msgs = 0
    dropped_tokens = 0

    keep_head = (
        2
        if len(packed) >= 2
        and isinstance(packed[1].get("content"), str)
        and packed[1]["content"].startswith(summary_header_prefix)
        else 1
    )

    # Drop older user/assistant messages first, keep system + summary head
    while toks() > input_budget and len(packed) > keep_head + 1:
        dropped = packed.pop(keep_head)
        try:
            dropped_tokens += int(approx_tokens(dropped.get("content", "")))
            dropped_msgs += 1
        except Exception:
            pass

    # If still over budget, shrink the summary body (tail keep to retain latest context)
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        summary_msg = packed[1]
        txt = summary_msg.get("content", "")
        n = max(min_keep, int(len(txt) * keep_ratio))
        try:
            PACK_TELEMETRY["finalTrimSummaryShrunkFromChars"] = len(txt)
        except Exception:
            pass

        summary_msg["content"] = txt[-n:]

        try:
            PACK_TELEMETRY["finalTrimSummaryShrunkToChars"] = len(summary_msg["content"])
            PACK_TELEMETRY["finalTrimSummaryDroppedChars"] = int(
                max(
                    0,
                    int(PACK_TELEMETRY["finalTrimSummaryShrunkFromChars"])
                    - int(PACK_TELEMETRY["finalTrimSummaryShrunkToChars"]),
                )
            )
        except Exception:
            pass

    # As a last resort, remove the summary message entirely
    if toks() > input_budget and keep_head == 2 and len(packed) >= 2:
        removed = packed.pop(1)
        try:
            dropped_tokens += int(approx_tokens(removed.get("content", "")))
            dropped_msgs += 1
        except Exception:
            pass

    # Still over? Start trimming recent tail
    while toks() > input_budget and len(packed) > 2:
        removed = packed.pop(2 if len(packed) > 3 else 1)
        try:
            dropped_tokens += int(approx_tokens(removed.get("content", "")))
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
    cfg = _S()

    def _tok():
        try:
            return count_prompt_tokens(packed)
        except Exception:
            return 999_999

    start_tokens = _tok()
    overage = start_tokens - input_budget
    PACK_TELEMETRY["rollStartTokens"] = int(start_tokens)
    PACK_TELEMETRY["rollOverageTokens"] = int(overage)

    if overage <= int(cfg.get("skip_overage_lt", 128)):
        packed = _final_safety_trim(packed, input_budget)
        PACK_TELEMETRY["rollEndTokens"] = int(count_prompt_tokens(packed))
        return packed, summary

    peels_done = 0
    peeled_n = 0

    max_peel_per_turn = int(cfg.get("max_peel_per_turn", 1))
    if len(recent) > 6 and peels_done < max_peel_per_turn:
        peel_min = int(cfg.get("peel_min", 3))
        peel_frac = float(cfg.get("peel_frac", 0.2))
        peel_max = int(cfg.get("peel_max", 12))

        target = max(peel_min, min(peel_max, int(len(recent) * peel_frac)))
        peel = []
        for _ in range(min(target, len(recent))):
            peel.append(recent.popleft())
        peeled_n = len(peel)

        # Summarize peeled messages
        t0_sum = time.time()
        new_sum, _used_llm = summarize_chunks(peel)
        PACK_TELEMETRY["summarySec"] += float(time.time() - t0_sum)

        bullet_prefix = cfg.get("bullet_prefix", "- ")
        if new_sum.startswith(bullet_prefix):
            summary = (summary + "\n" + new_sum).strip() if summary else new_sum
        else:
            summary = new_sum

        # Compress summary
        t0_comp = time.time()
        summary = _compress_summary_block(summary)
        PACK_TELEMETRY["compressSec"] += float(time.time() - t0_comp)

        try:
            PACK_TELEMETRY["rollPeeledMsgs"] = int(peeled_n)
            PACK_TELEMETRY["rollNewSummaryChars"] = len(summary)
            PACK_TELEMETRY["rollNewSummaryTokensApprox"] = int(approx_tokens(summary))
        except Exception:
            pass

        summary_header_prefix = cfg.get("summary_header_prefix", "## Summary\n")
        packed = [
            {"role": "user", "content": system_text},
            {"role": "user", "content": summary_header_prefix + summary},
            *list(recent),
        ]

    # Final safety trim to budget
    t0_trim = time.time()
    packed = _final_safety_trim(packed, input_budget)
    PACK_TELEMETRY["finalTrimSec"] += float(time.time() - t0_trim)

    end_tokens = count_prompt_tokens(packed)
    PACK_TELEMETRY["rollEndTokens"] = int(end_tokens)
    return packed, summary
