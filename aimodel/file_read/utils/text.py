from __future__ import annotations

import re

from ..core.logging import get_logger

log = get_logger(__name__)


def clean_ws(s: str | None) -> str:
    return " ".join((s or "").split())


def strip_wrappers(
    text: str, *, trim_whitespace: bool, split_on_blank: bool, header_regex: str | None
) -> str:
    t = text or ""
    if trim_whitespace:
        t = t.strip()
    if not header_regex and not split_on_blank:
        return t
    head = t
    if split_on_blank:
        head = t.split("\n\n", 1)[0]
    if header_regex:
        try:
            rx = re.compile(header_regex)
            out = []
            for ln in head.splitlines():
                if rx.match(ln):
                    break
                out.append(ln)
            core = " ".join(" ".join(out).split())
            return core if core else t
        except Exception:
            return head
    return head
