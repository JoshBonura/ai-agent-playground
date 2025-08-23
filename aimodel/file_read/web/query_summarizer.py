# aimodel/file_read/web/query_summarizer.py
from __future__ import annotations
from typing import Any
import re

_PROMPT = """Summarize the user's request into a concise web search query.
Keep only the key entities and terms.
Do not explain, and do not surround the result in quotation marks or other punctuation.
You may only delete non-essential words. Do not add, replace, reorder, or paraphrase any words.
Keep the original word order. Output only the query text.

User: {text}
Query:"""

def _tokens(s: str) -> set[str]:
    # simple, generic normalization (no term lists)
    return set(re.findall(r"\w+", (s or "").lower()))

def summarize_query(llm: Any, user_text: str) -> str:
    txt = (user_text or "").strip()
    print(f"[SUMMARIZER] IN user_text={txt!r}")

    # 1) Bypass LLM for tiny inputs to avoid paraphrase drift
    if len(txt) <= 32 and len(txt.split()) <= 3:
        print(f"[SUMMARIZER] BYPASS (short) -> {txt!r}")
        return txt

    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": _PROMPT.format(text=txt)}],
        max_tokens=32,
        temperature=0.0,
        top_p=1.0,           # fully greedy; reduces unintended paraphrasing
        stream=False,
        stop=["\n", "</s>"],
    )
    result = (out["choices"][0]["message"]["content"] or "").strip()

    # 2) Similarity fallback (generic, no special terms)
    src_toks = _tokens(txt)
    out_toks = _tokens(result)
    if not result or not out_toks:
        print(f"[SUMMARIZER] RETAIN (empty/none) -> {txt!r}")
        print(f"[SUMMARIZER] OUT query={txt!r}")
        return txt

    jaccard = (len(src_toks & out_toks) / len(src_toks | out_toks)) if (src_toks or out_toks) else 1.0
    if jaccard < 0.6:
        print(f"[SUMMARIZER] RETAIN (low overlap {jaccard:.2f}) -> {txt!r}")
        print(f"[SUMMARIZER] OUT query={txt!r}")
        return txt

    print(f"[SUMMARIZER] OUT query={result!r} (overlap {jaccard:.2f})")
    return result
