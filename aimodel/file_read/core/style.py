from __future__ import annotations

import re

from ..core.logging import get_logger
from .settings import SETTINGS

log = get_logger(__name__)


def get_style_sys() -> str:
    return SETTINGS.get("style_sys", "")


def extract_style_and_prefs(user_text: str) -> tuple[str | None, bool, bool]:
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

    style_inst: str | None = None
    if style_match:
        raw = style_match.group("style").strip().rstrip(".")
        style_inst = template.format(style=raw)

    return style_inst, False, False
