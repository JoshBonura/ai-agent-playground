# ===== aimodel/file_read/rag/ingest/csv_ingest.py =====
from __future__ import annotations
from typing import Tuple, List
import io, re, csv
from ...core.settings import SETTINGS

_WS_RE = re.compile(r"[ \t]+")
_PHANTOM_RX = re.compile(r"^\d+_\d+$")

def _squeeze_spaces_inline(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip()

def extract_csv(data: bytes) -> Tuple[str, str]:
    S = SETTINGS.effective
    max_chars = int(S().get("csv_value_max_chars"))
    quote_strings = bool(S().get("csv_quote_strings"))
    header_normalize = bool(S().get("csv_header_normalize"))
    max_rows = int(S().get("csv_infer_max_rows"))
    max_cols = int(S().get("csv_infer_max_cols"))

    def clip(s: str) -> str:
        if max_chars > 0 and len(s) > max_chars:
            return s[:max_chars] + "…"
        return s

    def fmt_val(v) -> str:
        if v is None:
            return ""
        s = str(v)
        if "\n" in s or "\r" in s:
            s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        s = clip(_squeeze_spaces_inline(s))
        if quote_strings and re.search(r"[^A-Za-z0-9_.-]", s):
            return f"\"{s}\""
        return s

    def normalize_header(h: str) -> str:
        if not header_normalize:
            return h
        s = (h or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s or h

    def rightmost_nonempty_header(headers: List[str]) -> int:
        for i in range(len(headers) - 1, -1, -1):
            h = headers[i]
            if h and not h.isspace():
                return i
        return -1

    def keep_headers(headers: List[str]) -> List[int]:
        keep = []
        for i, h in enumerate(headers):
            hn = (h or "").strip().lower()
            if not hn:
                continue
            if _PHANTOM_RX.fullmatch(hn) or hn in {"0"}:
                continue
            keep.append(i)
        return keep or list(range(len(headers)))

    def _row_blank_csv(row: List[str]) -> bool:
        if row is None:
            return True
        for c in row:
            if c is None:
                continue
            if str(c).strip():
                return False
        return True

    txt = io.StringIO(data.decode("utf-8", errors="ignore"))
    sample = txt.read(2048)
    txt.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
    except Exception:
        dialect = csv.excel
    reader = csv.reader(txt, dialect)
    rows = list(reader)
    if not rows:
        return "", "text/plain"

    n = len(rows)
    lines: List[str] = []
    lines.append("# Sheet: CSV")

    i = 0
    while i < n:
        while i < n and _row_blank_csv(rows[i]):
            i += 1
        if i >= n:
            break

        start = i
        while i < n and not _row_blank_csv(rows[i]):
            i += 1
        end = i - 1
        if start > end:
            continue

        headers_raw = (rows[start] if start < n else [])[:max_cols]
        norm_headers = [normalize_header(fmt_val(h)) for h in headers_raw]
        rmax = rightmost_nonempty_header(norm_headers)
        if rmax >= 0:
            norm_headers = norm_headers[: rmax + 1]
        norm_headers = norm_headers[:max_cols]
        keep_idx = keep_headers(norm_headers)
        kept_headers = [norm_headers[j] for j in keep_idx]

        total_rows_block = (end - start + 1)
        use_rows = total_rows_block if max_rows <= 0 else min(total_rows_block, max_rows + 1)
        total_cols_block = len(kept_headers)
        if max_cols > 0:
            total_cols_block = min(total_cols_block, max_cols)

        lines.append(f"## Table: CSV!R{start+1}-{start+use_rows},C1-{max(total_cols_block,1)}")
        if any(kept_headers):
            lines.append("headers: " + ", ".join(h for h in kept_headers if h))
        lines.append("")

        data_start = start + 1
        data_end = min(end, start + use_rows - 1)
        usable_cols_for_slice = min(len(norm_headers), max_cols if max_cols > 0 else len(norm_headers))
        for r in range(data_start, data_end + 1):
            row_vals_raw = rows[r][:usable_cols_for_slice] if r < n else []
            vals = [fmt_val(c) for c in row_vals_raw]
            vals = [vals[j] if j < len(vals) else "" for j in keep_idx]
            while vals and (vals[-1] == "" or vals[-1] is None):
                vals.pop()
            if not any(vals):
                continue

            pairs: List[str] = []
            for h, v in zip(kept_headers, vals):
                if h and v:
                    pairs.append(f"{h}={v}")

            excel_row_num = r + 1
            lines.append(f"### Row {excel_row_num} — CSV")
            lines.append(", ".join(pairs) if pairs else ", ".join(vals))
            lines.append("")

    return "\n".join(lines).strip() + "\n", "text/plain"
