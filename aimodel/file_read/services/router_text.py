from __future__ import annotations
from typing import Optional, List
from ..core.settings import SETTINGS


def compose_router_text(
    recent,
    latest_user_text: str,
    summary: str,
    *,
    tail_turns: Optional[int] = None,
    summary_chars: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    eff = SETTINGS.effective()
    tt = int(eff["router_tail_turns"]) if tail_turns is None else int(tail_turns)
    sc = int(eff["router_summary_chars"]) if summary_chars is None else int(summary_chars)
    mc = int(eff["router_max_chars"]) if max_chars is None else int(max_chars)
    context_label = eff["router_context_label"]
    summary_label = eff["router_summary_label"]

    parts: List[str] = []
    if latest_user_text:
        parts.append((latest_user_text or "").strip())

    try:
        recent_list = list(recent)
    except Exception:
        recent_list = []

    tail_src = recent_list[-tt:] if tt > 0 else []
    tail_lines: List[str] = []
    for m in reversed(tail_src):
        if not isinstance(m, dict):
            continue
        c = (m.get("content") or "").strip()
        if not c:
            continue
        role = (m.get("role") or "user").strip()
        tail_lines.append(f"{role}: {c}")

    if tail_lines:
        parts.append(context_label + "\n" + "\n".join(tail_lines))

    if summary:
        s = summary.strip()
        if sc > 0 and len(s) > sc:
            s = s[-sc:]
        parts.append(summary_label + "\n" + s)

    out = "\n\n".join(parts).strip()
    if len(out) > mc:
        out = out[:mc].rstrip()
    return out
