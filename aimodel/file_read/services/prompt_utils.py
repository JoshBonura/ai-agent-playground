from __future__ import annotations
import json
from datetime import datetime
from typing import Dict, List


def now_str() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def chars_len(msgs: List[object]) -> int:
    total = 0
    for m in msgs:
        if isinstance(m, dict):
            c = m.get("content")
        else:
            c = m
        if isinstance(c, str):
            total += len(c)
        elif c is None:
            continue
        else:
            try:
                total += len(json.dumps(c, ensure_ascii=False))
            except Exception:
                pass
    return total

