# aimodel/file_read/web/router_ai.py
from __future__ import annotations
from typing import Tuple, Optional, Any
import json
import re

# IMPORTANT: Double braces to escape JSON in .format()
_PROMPT = (
    "You ONLY output JSON. Task: Decide if the user's question needs LIVE WEB results "
    "(news, prices, schedules, laws, 'today/now/latest', changing facts). "
    'Return exactly: {{"need": true|false, "query": "<concise web query or empty>"}} '
    "No extra text.\n\nUser: {text}\nJSON:"
)

def _force_json(s: str) -> Optional[dict]:
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

def decide_web(llm: Any, user_text: str) -> Tuple[bool, Optional[str]]:
    """
    General-purpose router with no hardcoded heuristics.
    - Lets the model decide if web is needed.
    - Supports explicit overrides via "web:" / "search:".
    - Returns (need_web, query_if_needed).
    """
    if not user_text or not user_text.strip():
        return (False, None)

    t = user_text.strip()
    low = t.lower()

    # Explicit override: allow caller to force web and optionally supply a query
    if low.startswith("web:") or low.startswith("search:"):
        q = t.split(":", 1)[1].strip() or t
        return (True, q)

    # Model-based decision (no regex/rule hardcodes)
    try:
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": _PROMPT.format(text=t)}],
            max_tokens=64,
            temperature=0.0,
            top_p=0.9,
            stream=False,
            stop=["</s>", "\n\n"],
        )
        text = out["choices"][0]["message"]["content"].strip()
    except Exception:
        # If the decision model fails, default to no web to avoid surprises
        return (False, None)

    data = _force_json(text) or {}
    need = bool(data.get("need", False))
    query = (str(data.get("query") or "")).strip() or (t if need else None)
    return (need, query if need else None)
