# aimodel/file_read/memory.py
from __future__ import annotations
import math
from typing import Dict, List
from collections import deque
from ..model_runtime import get_llm     # <-- use runtime, not a global llm
from .style import STYLE_SYS
from ..store import get_summary as store_get_summary

SESSIONS: Dict[str, Dict] = {}

def get_session(session_id: str):
    st = SESSIONS.setdefault(session_id, {
        "summary": "",
        "recent": deque(maxlen=50),
        "style": STYLE_SYS,
        "short": False,
        "bullets": False,
    })
    # seed once from storage if empty
    if not st["summary"]:
        try:
            st["summary"] = store_get_summary(session_id) or ""
        except Exception:
            pass
    return st

def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))

def count_prompt_tokens(msgs: List[Dict[str, str]]) -> int:
    return sum(approx_tokens(m["content"]) + 4 for m in msgs)

def summarize_chunks(chunks: List[Dict[str,str]]) -> str:
    text = "\n".join(f'{m["role"]}: {m["content"]}' for m in chunks)
    prompt = f"Summarize crisply the key points and decisions:\n\n{text}\n\nSummary:"
    llm = get_llm()
    out = llm.create_chat_completion(
        messages=[{"role":"system","content":"Be concise."},
                  {"role":"user","content":prompt}],
        max_tokens=240, temperature=0.2, top_p=0.9, stream=False
    )
    return out["choices"][0]["message"]["content"].strip()

def build_system(style: str, short: bool, bullets: bool) -> str:
    parts = [STYLE_SYS]
    if style and style != STYLE_SYS:
        parts.append(style)
    if short:
        parts.append("Keep answers extremely brief: max 2 sentences OR 5 short bullets.")
    if bullets:
        parts.append("Use bullet points when possible; each bullet under 15 words.")
    parts.append("Always follow the user's most recent style instructions.")
    return " ".join(parts)

def pack_messages(style: str, short: bool, bullets: bool, summary, recent, max_ctx, out_budget):
    input_budget = max_ctx - out_budget - 256
    sys_text = build_system(style, short, bullets)

    # Put “system” guidance into a *user* prologue for Mistral-Instruct
    prologue = [{"role": "user", "content": sys_text}]
    if summary:
        prologue.append({"role": "user", "content": f"Conversation summary so far:\n{summary}"})

    packed = prologue + list(recent)
    return packed, input_budget

def roll_summary_if_needed(packed, recent, summary, input_budget, system_text):
    while count_prompt_tokens(packed) > input_budget and len(recent) > 6:
        peel = []
        for _ in range(max(4, len(recent) // 5)):
            peel.append(recent.popleft())
        new_sum = summarize_chunks(peel)
        summary = (summary + "\n" + new_sum).strip() if summary else new_sum

        # Rebuild using *user* role, matching pack_messages
        packed = [
            {"role": "user", "content": system_text},
            {"role": "user", "content": f"Conversation summary so far:\n{summary}"},
            *list(recent),
        ]
    return packed, summary
