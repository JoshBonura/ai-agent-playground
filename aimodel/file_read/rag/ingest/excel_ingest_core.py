# ===== aimodel/file_read/rag/ingest/excel_ingest_core.py =====
from __future__ import annotations
from typing import List, Tuple
import re

_PII_HDRS = {"ssn","social_security_number","email","phone","dob"}
_PHANTOM_RX = re.compile(r"^\d+_\d+$")

def row_blank(ws, r: int, min_c: int, max_c: int) -> bool:
    for c in range(min_c, max_c + 1):
        v = ws.cell(row=r, column=c).value
        if v not in (None, "") and not (isinstance(v, str) and not v.strip()):
            return False
    return True

def scan_blocks_by_blank_rows(ws, min_c: int, min_r: int, max_c: int, max_r: int):
    r = min_r
    while r <= max_r:
        while r <= max_r and row_blank(ws, r, min_c, max_c):
            r += 1
        if r > max_r:
            break
        start = r
        while r <= max_r and not row_blank(ws, r, min_c, max_c):
            r += 1
        end = r - 1
        yield (min_c, start, max_c, end)

def rightmost_nonempty_header(headers: List[str]) -> int:
    for i in range(len(headers) - 1, -1, -1):
        h = headers[i]
        if h and not h.isspace():
            return i
    return -1

def drop_bad_columns(headers: List[str]) -> List[int]:
    keep = []
    for i, h in enumerate(headers):
        hn = (h or "").strip().lower()
        if not hn:
            continue
        if _PHANTOM_RX.fullmatch(hn) or hn in {"0"}:
            continue
        if hn in _PII_HDRS:
            continue
        keep.append(i)
    return keep or list(range(len(headers)))

def select_indices(seq: List[str], idxs: List[int]) -> List[str]:
    out = []
    for i in idxs:
        out.append(seq[i] if i < len(seq) else "")
    return out
