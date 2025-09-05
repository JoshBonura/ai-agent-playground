from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import re, os
from ..core.settings import SETTINGS

_TABLE_RE = re.compile(r"^##\s*Table:\s*(?P<sheet>[^!]+)!\s*R(?P<r1>\d+)-(?P<r2>\d+),C(?P<c1>\d+)-(?P<c2>\d+)", re.MULTILINE)
_ROW_RE = re.compile(r"^#{0,3}\s*Row\s+(?P<row>\d+)\s+—\s+(?P<sheet>[^\r\n]+)", re.MULTILINE)


def is_csv_source(src: str) -> bool:
    try:
        _, ext = os.path.splitext(src.lower())
        return ext in {".csv", ".tsv"}
    except Exception:
        return False


def is_xlsx_source(src: str) -> bool:
    try:
        _, ext = os.path.splitext(src.lower())
        return ext in {".xlsx", ".xlsm", ".xls"}
    except Exception:
        return False


def _capture_table_block(text: str) -> Optional[str]:
    m = _TABLE_RE.search(text or "")
    if not m:
        return None
    start = m.start()
    end = len(text)
    nxt = re.search(r"^\s*$", text[m.end():], re.MULTILINE)
    if nxt:
        end = m.end() + nxt.start()
    return text[start:end].strip()


def _capture_row_block(text: str, row_num: int, sheet: str) -> Optional[str]:
    if not text:
        return None
    pat = re.compile(rf"^#{0,3}\s*Row\s+{row_num}\s+—\s+{re.escape(sheet)}[^\n]*\n(?P<body>.*?)(?:\n\s*\n|$)", re.MULTILINE | re.DOTALL)
    m = pat.search(text)
    if not m:
        pat2 = re.compile(rf"^\s*{row_num}\s+—\s+{re.escape(sheet)}[^\n]*\n(?P<body>.*?)(?:\n\s*\n|$)", re.MULTILINE | re.DOTALL)
        m = pat2.search(text)
        if not m:
            return None
    head = f"### Row {row_num} — {sheet}"
    body = (m.group("body") or "").strip()
    if not body:
        return head
    return f"{head}\n{body}"


def _collect_tabular_hits(hits: List[dict]) -> Dict[str, Any]:
    headers: Dict[Tuple[str, str, int, int, int, int], Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    for h in hits:
        src = str(h.get("source") or "")
        body = (h.get("text") or "").strip()

        for mt in _TABLE_RE.finditer(body):
            sheet = mt.group("sheet").strip()
            r1 = int(mt.group("r1")); r2 = int(mt.group("r2"))
            c1 = int(mt.group("c1")); c2 = int(mt.group("c2"))
            key = (src, sheet, r1, r2, c1, c2)
            if key not in headers:
                tb = _capture_table_block(body)
                headers[key] = {
                    "source": src, "sheet": sheet,
                    "r1": r1, "r2": r2, "c1": c1, "c2": c2,
                    "text": tb or "", "score": float(h.get("score") or 0.0)
                }
            else:
                headers[key]["score"] = max(headers[key]["score"], float(h.get("score") or 0.0))

        for mr in _ROW_RE.finditer(body):
            rn = int(mr.group("row"))
            sheet = mr.group("sheet").strip()
            rows.append({"source": src, "sheet": sheet, "row": rn, "hit": h, "score": float(h.get("score") or 0.0)})
    return {"headers": headers, "rows": rows}


def _pair_rows_with_headers(collected: Dict[str, Any]) -> Dict[Tuple[str, str, int, int, int, int], Dict[str, Any]]:
    headers = collected["headers"]
    rows = collected["rows"]
    groups: Dict[Tuple[str, str, int, int, int, int], Dict[str, Any]] = {}
    for r in rows:
        src = r["source"]; sheet = r["sheet"]; rown = r["row"]
        match_key = None
        for key in headers.keys():
            s, sh, r1, r2, c1, c2 = key
            if s == src and sh == sheet and r1 <= rown <= r2:
                match_key = key
                break
        if not match_key:
            continue
        g = groups.setdefault(match_key, {"header": headers[match_key], "rows": []})
        g["rows"].append(r)
    return groups


def _render_tabular_groups(
    groups: Dict[Tuple[str, str, int, int, int, int], Dict[str, Any]],
    preferred_sources: Optional[List[str]] = None
) -> List[str]:
    total_budget = int(SETTINGS.get("rag_total_char_budget"))
    max_row_snippets = int(SETTINGS.get("rag_tabular_rows_per_table"))
    per_row_max = int(SETTINGS.get("rag_max_chars_per_chunk"))
    preamble = str(SETTINGS.get("rag_block_preamble") or "")
    preamble = preamble if not preamble or preamble.endswith(":") else preamble + ":"

    pref = set(s.strip().lower() for s in (preferred_sources or []) if s)
    boost = float(SETTINGS.get("rag_new_upload_score_boost"))

    lines: List[str] = [preamble]
    used = len(lines[0]) + 1

    def _group_score(key):
        base = groups[key]["header"]["score"]
        src = str(groups[key]["header"]["source"] or "").strip().lower()
        return base * (1.0 + boost) if src in pref else base

    keys_sorted = sorted(groups.keys(), key=_group_score, reverse=True)

    for key in keys_sorted:
        hdr = groups[key]["header"]
        hdr_text = (hdr.get("text") or "").strip()
        if not hdr_text:
            hdr_text = f"## Table: {hdr['sheet']}!R{hdr['r1']}-{hdr['r2']},C{hdr['c1']}-{hdr['c2']}"
        hdr_cost = len(hdr_text) + 1
        if used + hdr_cost > total_budget:
            break
        lines.append(hdr_text)
        used += hdr_cost

        row_list = sorted(groups[key]["rows"], key=lambda r: r["score"], reverse=True)[:max_row_snippets]
        for r in row_list:
            body = (r["hit"].get("text") or "")
            row_block = _capture_row_block(body, r["row"], r["sheet"]) or ""
            if not row_block:
                continue
            row_snip = row_block[:per_row_max].strip()
            row_cost = len(row_snip) + 1
            if used + row_cost > total_budget:
                break
            lines.append(row_snip)
            used += row_cost

        if used >= total_budget:
            break

    return lines


def make_rag_block_tabular(hits: List[dict], preferred_sources: Optional[List[str]] = None) -> Optional[str]:
    if not hits:
        return None
    # Only keep sources that look like CSV/Excel to avoid mixing generic text
    tabular_hits = [
        h for h in hits
        if is_xlsx_source(str(h.get("source") or "")) or is_csv_source(str(h.get("source") or ""))
    ]
    if not tabular_hits:
        return None
    collected = _collect_tabular_hits(tabular_hits)
    groups = _pair_rows_with_headers(collected)
    if not groups:
        return None
    lines = _render_tabular_groups(groups, preferred_sources=preferred_sources)
    return "\n".join(lines)
