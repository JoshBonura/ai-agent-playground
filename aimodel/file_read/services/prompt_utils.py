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


def dump_full_prompt(
    messages: List[Dict[str, object]],
    *,
    params: Dict[str, object],
    session_id: str,
) -> None:
    try:
        print(f"[{now_str()}] PROMPT DUMP BEGIN session={session_id} msgs={len(messages)}")
        print(json.dumps({"messages": messages, "params": params}, ensure_ascii=False, indent=2))
        print(f"[{now_str()}] PROMPT DUMP END   session={session_id}")
    except Exception as e:
        print(f"[{now_str()}] PROMPT DUMP ERROR session={session_id} err={type(e).__name__}: {e}")
