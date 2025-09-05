# aimodel/file_read/services/attachments.py
from __future__ import annotations
from typing import Any, Iterable, Optional, List


def att_get(att: Any, key: str, default=None):
    try:
        return att.get(key, default)          
    except AttributeError:
        return getattr(att, key, default)    


def join_attachment_names(attachments: Optional[Iterable[Any]]) -> str:
    if not attachments:
        return ""
    names: List[str] = [att_get(a, "name") for a in attachments]  
    names = [n for n in names if n]
    return ", ".join(names)
