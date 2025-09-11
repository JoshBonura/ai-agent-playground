# ===== aimodel/file_read/rag/ingest/xls_ingest.py =====
from __future__ import annotations

import re
from datetime import date, datetime, time

from ...core.logging import get_logger
from ...core.settings import SETTINGS

log = get_logger(__name__)

_WS_RE = re.compile(r"[ \t]+")


def _squeeze_spaces_inline(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip()


def extract_xls(data: bytes) -> tuple[str, str]:
    try:
        import xlrd
    except Exception:
        return (data.decode("utf-8", errors="replace"), "text/plain")

    S = SETTINGS.effective

    sig = int(S().get("excel_number_sigfigs"))
    maxp = int(S().get("excel_decimal_max_places"))
    trim = bool(S().get("excel_trim_trailing_zeros"))
    drop_midnight = bool(S().get("excel_dates_drop_time_if_midnight"))
    time_prec = str(S().get("excel_time_precision"))
    max_chars = int(S().get("excel_value_max_chars"))
    quote_strings = bool(S().get("excel_quote_strings"))

    INFER_MAX_ROWS = int(S().get("excel_infer_max_rows"))
    INFER_MAX_COLS = int(S().get("excel_infer_max_cols"))
    INFER_MIN_HEADER_FILL = float(S().get("excel_infer_min_header_fill_ratio", 0.5))
    EMIT_KEYVALUES = bool(S().get("excel_emit_key_values"))
    EMIT_CELL_ADDR = bool(S().get("excel_emit_cell_addresses"))
    HEADER_NORMALIZE = bool(S().get("excel_header_normalize"))

    def clip(s: str) -> str:
        if max_chars > 0 and len(s) > max_chars:
            return s[:max_chars] + "…"
        return s

    def fmt_number(v) -> str:
        try:
            s = format(float(v), f".{sig}g") if sig > 0 else f"{float(v):.{maxp}f}"
        except Exception:
            s = str(v)
        if "e" in s.lower():
            try:
                s = f"{float(v):.{maxp}f}"
            except Exception:
                pass
        if trim and "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    def fmt_date(dt: datetime) -> str:
        if drop_midnight and isinstance(dt, datetime) and dt.time() == time(0, 0, 0):
            return dt.date().isoformat()
        return dt.strftime("%Y-%m-%d %H:%M" if time_prec == "minute" else "%Y-%m-%d %H:%M:%S")

    def fmt_time(t: time) -> str:
        return t.strftime("%H:%M" if time_prec == "minute" else "%H:%M:%S")

    def fmt_val(v) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return fmt_number(v)
        if isinstance(v, datetime):
            return fmt_date(v)
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, time):
            return fmt_time(v)
        s = str(v)
        if "\n" in s or "\r" in s:
            s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        s = clip(_squeeze_spaces_inline(s))
        if quote_strings and re.search(r"[^A-Za-z0-9_.-]", s):
            return f'"{s}"'
        return s

    def normalize_header(h: str) -> str:
        if not HEADER_NORMALIZE:
            return h
        s = (h or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s or h

    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception:
        return (data.decode("utf-8", errors="replace"), "text/plain")

    datemode = book.datemode

    def xlrd_cell_to_py(cell):
        ctype, value = cell.ctype, cell.value
        if ctype == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate_as_datetime(value, datemode)
            except Exception:
                return value
        if ctype == xlrd.XL_CELL_NUMBER:
            return float(value)
        if ctype == xlrd.XL_CELL_BOOLEAN:
            return bool(value)
        return value

    lines: list[str] = []

    for sheet in book.sheets():
        nrows = min(sheet.nrows or 0, INFER_MAX_ROWS)
        ncols = min(sheet.ncols or 0, INFER_MAX_COLS)
        if nrows == 0 or ncols == 0:
            continue

        headers_raw = []
        header_fill = 0
        for c in range(ncols):
            v = xlrd_cell_to_py(sheet.cell(0, c))
            s = "" if v is None else str(v).strip()
            if s:
                header_fill += 1
            headers_raw.append(s)

        fill_ratio = header_fill / max(1, ncols)
        start_row = 1
        if fill_ratio < INFER_MIN_HEADER_FILL and nrows >= 2:
            headers_raw = []
            for c in range(ncols):
                v = xlrd_cell_to_py(sheet.cell(1, c))
                s = "" if v is None else str(v).strip()
                headers_raw.append(s)
            start_row = 2

        norm_headers = [normalize_header(h) for h in headers_raw]

        lines.append(f"# Sheet: {sheet.name}")

        if EMIT_KEYVALUES and ncols == 2:
            textish = valueish = rows = 0
            for r in range(start_row, nrows):
                a = xlrd_cell_to_py(sheet.cell(r, 0))
                b = xlrd_cell_to_py(sheet.cell(r, 1))
                if a is None and b is None:
                    continue
                rows += 1
                if isinstance(a, str):
                    textish += 1
                if isinstance(b, (int, float, datetime, date, time)):
                    valueish += 1
            if rows >= 3 and textish / max(1, rows) >= 0.6 and valueish / max(1, rows) >= 0.6:
                lines.append("## Key/Values")
                for r in range(start_row, nrows):
                    k = fmt_val(xlrd_cell_to_py(sheet.cell(r, 0)))
                    v = fmt_val(xlrd_cell_to_py(sheet.cell(r, 1)))
                    if not k and not v:
                        continue
                    lines.append(f"- {k}: {v}" if k else f"- : {v}")
                lines.append("")
                continue

        lines.append("## Inferred Table")
        if any(h for h in norm_headers):
            lines.append("headers: " + ", ".join(h for h in norm_headers if h))

        for r in range(start_row, nrows):
            row_vals: list[str] = []
            for c in range(ncols):
                val = fmt_val(xlrd_cell_to_py(sheet.cell(r, c)))
                if val:
                    row_vals.append(val if not EMIT_CELL_ADDR else f"{val}")
            if row_vals:
                lines.append("row: " + ", ".join(row_vals))
        lines.append("")

    text = "\n".join(line.rstrip() for line in lines if line is not None).strip()
    return (text + "\n" if text else ""), "text/plain"
