from __future__ import annotations
import re
from typing import Optional, Tuple
from .settings import SETTINGS

def get_style_sys() -> str:
    return SETTINGS.get("style_sys", "")

def extract_style_and_prefs(user_text: str) -> Tuple[Optional[str], bool, bool]:
    S = SETTINGS.effective()
    pats = S.get("style_patterns", {})
    template = S.get("style_template", "You must talk like {style}.")

    compiled = []
    for key in ["talk_like", "respond_like", "from_now", "be"]:
        if key in pats:
            compiled.append(re.compile(pats[key], re.I))

    t = user_text.strip()
    style_match = None
    for pat in compiled:
        style_match = pat.search(t)
        if style_match:
            break

    style_inst: Optional[str] = None
    if style_match:
        raw = style_match.group("style").strip().rstrip(".")
        style_inst = template.format(style=raw)

    return style_inst, False, False
