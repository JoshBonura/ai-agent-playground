from __future__ import annotations
import re
from typing import Optional, Tuple

STYLE_SYS = (
    "You are a helpful assistant. "
    "Always follow the user's explicit instructions carefully and exactly. "
    "Do not repeat yourself. Stay coherent and complete."
)

PAT_TALK_LIKE = re.compile(r"\btalk\s+like\s+(?P<style>[^.;\n]+)", re.I)
PAT_RESPOND_LIKE = re.compile(r"\brespond\s+like\s+(?P<style>[^.;\n]+)", re.I)
PAT_BE = re.compile(r"\bbe\s+(?P<style>[^.;\n]+)", re.I)
PAT_FROM_NOW = re.compile(r"\bfrom\s+now\s+on[, ]+\s*(?P<style>[^.;\n]+)", re.I)

def extract_style_and_prefs(user_text: str) -> Tuple[Optional[str], bool, bool]:
    t = user_text.strip()
    style_match = (
        PAT_TALK_LIKE.search(t)
        or PAT_RESPOND_LIKE.search(t)
        or PAT_FROM_NOW.search(t)
        or PAT_BE.search(t)
    )
    style_inst: Optional[str] = None
    if style_match:
        raw = style_match.group("style").strip().rstrip(".")
        style_inst = (
            f"You must talk like {raw}. "
            f"Stay in character but remain helpful and accurate. "
            f"Follow the user's latest style instructions."
        )
    return style_inst, False, False
