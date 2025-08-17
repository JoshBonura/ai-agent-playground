from __future__ import annotations
import math
from typing import Dict, List
from collections import deque
from .model import llm
from .style import STYLE_SYS

# Add prefs: short, bullets
# { sessionId: { "summary": str, "recent": deque, "style": str, "short": bool, "bullets": bool } }
SESSIONS: Dict[str, Dict] = {}

def get_session(session_id: str):
    return SESSIONS.setdefault(session_id, {
        "summary": "",
        "recent": deque(maxlen=50),
        "style": STYLE_SYS,
        "short": False,
        "bullets": False,
    })

def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))

def count_prompt_tokens(msgs: List[Dict[str, str]]) -> int:
    return sum(approx_tokens(m["content"]) + 4 for m in msgs)

def summarize_chunks(chunks: List[Dict[str,str]]) -> str:
    text = "\n".join(f'{m["role"]}: {m["content"]}' for m in chunks)
    prompt = f"Summarize crisply the key points and decisions:\n\n{text}\n\nSummary:"
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
        parts.append("Keep answers extremely brief: max 2 sentences OR 5 very short bullets.")
    if bullets:
        parts.append("Use bullet points when possible; each bullet under 15 words.")
    parts.append("Always follow the user’s most recent style instructions.")
    return " ".join(parts)

def pack_messages(style: str, short: bool, bullets: bool, summary: str, recent: deque,
                  max_ctx: int, out_budget: int):
    input_budget = max_ctx - out_budget - 256
    system = build_system(style, short, bullets)
    sys_msgs = [{"role": "system", "content": system}]
    if summary:
        sys_msgs.append({"role": "system", "content": f"Conversation summary so far:\n{summary}"})
    packed = sys_msgs + list(recent)
    return packed, input_budget

def roll_summary_if_needed(packed, recent, summary, input_budget, system_text):
    while count_prompt_tokens(packed) > input_budget and len(recent) > 6:
        peel = []
        for _ in range(max(4, len(recent) // 5)):
            peel.append(recent.popleft())
        new_sum = summarize_chunks(peel)
        summary = (summary + "\n" + new_sum).strip() if summary else new_sum
        packed = [
            {"role": "system", "content": system_text},
            {"role": "system", "content": f"Conversation summary so far:\n{summary}"},
            *list(recent),
        ]
    return packed, summary
