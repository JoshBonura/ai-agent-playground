from __future__ import annotations
from typing import Any, Iterable, Optional, List


def att_get(att: Any, key: str, default=None):
    """Safe accessor for dicts OR Pydantic models."""
    try:
        return att.get(key, default)          # dict-like
    except AttributeError:
        return getattr(att, key, default)     # model-like


def join_attachment_names(attachments: Optional[Iterable[Any]]) -> str:
    if not attachments:
        return ""
    names: List[str] = [att_get(a, "name") for a in attachments]  # type: ignore[list-item]
    names = [n for n in names if n]
    return ", ".join(names)
