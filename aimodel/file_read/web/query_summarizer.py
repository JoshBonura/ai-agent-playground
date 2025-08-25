# aimodel/file_read/web/query_summarizer.py
from __future__ import annotations
from typing import Any, Iterable
import re

from ..core.settings import SETTINGS

def _tokens(s: str) -> set[str]:
    return set(re.findall(r"\w+", (s or "").lower()))

def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]

def summarize_query(llm: Any, user_text: str) -> str:
    """
    Settings used (all optional; no in-code fallbacks):
      - query_sum_bypass_short_enabled : bool
      - query_sum_short_max_chars      : int
      - query_sum_short_max_words      : int
      - query_sum_prompt               : str (must contain '{text}')
      - query_sum_max_tokens           : int
      - query_sum_temperature          : float
      - query_sum_top_p                : float
      - query_sum_stop                 : list[str]
      - query_sum_overlap_check_enabled: bool
      - query_sum_overlap_jaccard_min  : float (0..1)
    """
    txt = (user_text or "").strip()
    print(f"[SUMMARIZER] IN user_text={txt!r}")

    # --- Bypass for very short queries (only if fully configured) ---
    bypass_enabled = SETTINGS.get("query_sum_bypass_short_enabled")
    short_chars = SETTINGS.get("query_sum_short_max_chars")
    short_words = SETTINGS.get("query_sum_short_max_words")
    if bypass_enabled is True and isinstance(short_chars, int) and isinstance(short_words, int):
        if len(txt) <= short_chars and len(txt.split()) <= short_words:
            print(f"[SUMMARIZER] BYPASS (short) -> {txt!r}")
            return txt

    # --- LLM prompt construction (only if prompt provided) ---
    prompt = SETTINGS.get("query_sum_prompt")
    if isinstance(prompt, str) and "{text}" in prompt:
        params = {}
        # Only include configured generation params; nothing hardcoded.
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

        params["stream"] = False  # summarizer uses non-streamed call

        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt.format(text=txt)}],
            **params,  # only what’s configured is sent
        )
        result = (out["choices"][0]["message"]["content"] or "").strip()
    else:
        # If no prompt configured, do not attempt to summarize — return original text.
        print("[SUMMARIZER] SKIP (no prompt configured) -> retain input")
        return txt

    # --- Optional overlap check (guard against paraphrase drift) ---
    overlap_enabled = SETTINGS.get("query_sum_overlap_check_enabled")
    j_min = SETTINGS.get("query_sum_overlap_jaccard_min")
    if overlap_enabled is True and isinstance(j_min, (int, float)):
        src_toks = _tokens(txt)
        out_toks = _tokens(result)
        if not result or not out_toks:
            print(f"[SUMMARIZER] RETAIN (empty/none) -> {txt!r}")
            print(f"[SUMMARIZER] OUT query={txt!r}")
            return txt
        jaccard = (len(src_toks & out_toks) / len(src_toks | out_toks)) if (src_toks or out_toks) else 1.0
        if jaccard < float(j_min):
            print(f"[SUMMARIZER] RETAIN (low overlap {jaccard:.2f} < {float(j_min):.2f}) -> {txt!r}")
            print(f"[SUMMARIZER] OUT query={txt!r}")
            return txt
        print(f"[SUMMARIZER] OUT query={result!r} (overlap {jaccard:.2f})")
        return result

    # If overlap check not enabled/configured, just return the LLM result.
    print(f"[SUMMARIZER] OUT query={result!r} (no overlap check)")
    return result
