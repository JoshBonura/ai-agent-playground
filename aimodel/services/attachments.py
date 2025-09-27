# aimodel/file_read/services/attachments.py
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..core.logging import get_logger

log = get_logger(__name__)


def att_get(att: Any, key: str, default=None):
    try:
        return att.get(key, default)
    except AttributeError:
        return getattr(att, key, default)


def join_attachment_names(attachments: Iterable[Any] | None) -> str:
    if not attachments:
        return ""
    names: list[str] = [att_get(a, "name") for a in attachments]
    names = [n for n in names if n]
    return ", ".join(names)
