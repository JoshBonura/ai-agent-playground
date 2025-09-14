# aimodel/file_read/web/query_summarizer.py
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..utils.streaming import safe_token_count_messages

log = get_logger(__name__)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"\w+", (s or "").lower()))


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def summarize_query(
    llm: Any,
    user_text: str,
    *,
    stop_ev: asyncio.Event | None = None,
) -> tuple[str, dict[str, Any]]:
    telemetry: dict[str, Any] = {}
    txt = (user_text or "").strip()

    if stop_ev and stop_ev.is_set():
        telemetry["cancelledAt"] = "start"
        return txt, telemetry

    bypass_enabled = SETTINGS.get("query_sum_bypass_short_enabled")
    short_chars = SETTINGS.get("query_sum_short_max_chars")
    short_words = SETTINGS.get("query_sum_short_max_words")
    if bypass_enabled is True and isinstance(short_chars, int) and isinstance(short_words, int):
        if len(txt) <= short_chars and len(txt.split()) <= short_words:
            telemetry.update({"bypass": True})
            return txt, telemetry
    telemetry.update({"bypass": False})

    prompt = SETTINGS.get("query_sum_prompt")
    if isinstance(prompt, str) and "{text}" in prompt:
        params = {}
        max_tokens = SETTINGS.get("query_sum_max_tokens")
        if isinstance(max_tokens, int):
            params["max_tokens"] = max_tokens
        temperature = SETTINGS.get("query_sum_temperature")
        if isinstance(temperature, (int, float)):
            params["temperature"] = float(temperature)
        top_p = SETTINGS.get("query_sum_top_p")
        if isinstance(top_p, (int, float)):
            params["top_p"] = float(top_p)
        stops = _as_list(SETTINGS.get("query_sum_stop"))
        if stops:
            params["stop"] = [str(s) for s in stops if isinstance(s, str)]
        params["stream"] = False

        if stop_ev and stop_ev.is_set():
            telemetry["cancelledAt"] = "before_llm"
            return txt, telemetry

        t_start = time.perf_counter()
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt.format(text=txt)}],
            **params,
        )
        elapsed = time.perf_counter() - t_start
        result = (out["choices"][0]["message"]["content"] or "").strip()
        in_tokens = (
            safe_token_count_messages(llm, [{"role": "user", "content": prompt.format(text=txt)}])
            or 0
        )
        out_tokens = safe_token_count_messages(llm, [{"role": "assistant", "content": result}]) or 0
        telemetry.update(
            {
                "elapsedSec": round(elapsed, 4),
                "inputTokens": in_tokens,
                "outputTokens": out_tokens,
            }
        )
    else:
        return txt, telemetry

    if stop_ev and stop_ev.is_set():
        telemetry["cancelledAt"] = "after_llm"
        return txt, telemetry

    overlap_enabled = SETTINGS.get("query_sum_overlap_check_enabled")
    j_min = SETTINGS.get("query_sum_overlap_jaccard_min")
    if overlap_enabled is True and isinstance(j_min, (int, float)):
        src_toks = _tokens(txt)
        out_toks = _tokens(result)
        if not result or not out_toks:
            telemetry.update({"overlapRetained": True, "overlapScore": 0.0})
            return txt, telemetry
        jaccard = (
            (len(src_toks & out_toks) / len(src_toks | out_toks)) if (src_toks or out_toks) else 1.0
        )
        telemetry.update({"overlapScore": round(jaccard, 4)})
        if jaccard < float(j_min):
            telemetry.update({"overlapRetained": True})
            return txt, telemetry
        telemetry.update({"overlapRetained": False})
        return result, telemetry

    return result, telemetry
