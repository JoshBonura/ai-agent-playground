from __future__ import annotations
from typing import Tuple, List
import io, re, hashlib
from datetime import datetime, date, time
from ...core.settings import SETTINGS
from .excel_ingest_core import (
    scan_blocks_by_blank_rows,
    rightmost_nonempty_header,
    select_indices,
)

_WS_RE = re.compile(r"[ \t]+")
def _squeeze_spaces_inline(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip()

def extract_excel(data: bytes) -> Tuple[str, str]:
    from openpyxl import load_workbook
    from openpyxl.utils import range_boundaries
    from openpyxl.worksheet.worksheet import Worksheet

    S = SETTINGS.effective

    sig = int(S().get("excel_number_sigfigs"))
    maxp = int(S().get("excel_decimal_max_places"))
    trim = bool(S().get("excel_trim_trailing_zeros"))
    drop_midnight = bool(S().get("excel_dates_drop_time_if_midnight"))
    time_prec = str(S().get("excel_time_precision"))
    max_chars = int(S().get("excel_value_max_chars"))
    quote_strings = bool(S().get("excel_quote_strings"))

    MAX_CELLS_PER_SHEET = int(S().get("excel_max_cells_per_sheet"))
    MAX_NR_PREVIEW = int(S().get("excel_named_range_preview"))
    EMIT_MERGED = bool(S().get("excel_emit_merged"))
    EMIT_CELLS = bool(S().get("excel_emit_cells"))

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
        if drop_midnight and dt.time() == time(0, 0, 0):
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
            return f"\"{s}\""
        return s

    def normalize_header(h: str) -> str:
        if not HEADER_NORMALIZE:
            return h
        s = (h or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s or h

    def _sheet_used_range(ws: Worksheet):
        from openpyxl.utils import range_boundaries
        if callable(getattr(ws, "calculate_dimension", None)):
            dim_ref = ws.calculate_dimension()
            try:
                min_c, min_r, max_c, max_r = range_boundaries(dim_ref)
                return min_c, min_r, max_c, max_r
            except Exception:
                pass
        return 1, 1, ws.max_column or 1, ws.max_row or 1

    def _cap_rows(min_r: int, max_r: int) -> int:
        return max_r if INFER_MAX_ROWS <= 0 else min(max_r, min_r + INFER_MAX_ROWS - 1)

    def _detect_key_value(ws: Worksheet, min_c, min_r, max_c, max_r) -> bool:
        if max_c - min_c + 1 != 2:
            return False
        limit_r = _cap_rows(min_r, max_r)
        textish, valueish, rows = 0, 0, 0
        for r in range(min_r, limit_r + 1):
            a = ws.cell(row=r, column=min_c).value
            b = ws.cell(row=r, column=min_c + 1).value
            if a is None and b is None:
                continue
            rows += 1
            if isinstance(a, str):
                textish += 1
            if isinstance(b, (int, float, datetime, date, time)):
                valueish += 1
        return rows >= 3 and textish / max(1, rows) >= 0.6 and valueish / max(1, rows) >= 0.6

    def _keep_and_rename_phantom(headers: List[str]) -> tuple[List[int], List[str]]:
        if len(headers) >= 2 and re.fullmatch(r"\d+_\d+$", (headers[1] or "")) and (headers[0] or ""):
            keep_idx = [0, 1]
            new_headers = headers[:]
            new_headers[1] = "value"
            return keep_idx, new_headers
        keep_idx = [i for i, h in enumerate(headers) if h and not re.fullmatch(r"\d+_\d+$", h)]
        new_headers = [headers[i] for i in keep_idx]
        return keep_idx, new_headers

    wb_vals = load_workbook(io.BytesIO(data), data_only=True, read_only=True)

    lines: List[str] = []
    ingest_id = hashlib.sha1(data).hexdigest()[:16]
    lines.append(f"# Ingest-ID: {ingest_id}")

    try:
        dn_obj = getattr(wb_vals, "defined_names", None)
        if dn_obj and getattr(dn_obj, "definedName", None):
            nr_out: List[str] = []
            for dn in dn_obj.definedName:
                if getattr(dn, "hidden", False):
                    continue
                try:
                    dests = list(dn.destinations)
                except Exception:
                    dests = []
                if not dests:
                    continue
                for sheet_name, ref in dests:
                    try:
                        ws = wb_vals[sheet_name]
                        min_c, min_r, max_c, max_r = range_boundaries(ref)
                        vals: List[str] = []
                        from openpyxl.utils import get_column_letter
                        gl = get_column_letter
                        for r in range(min_r, max_r + 1):
                            for c in range(min_c, max_c + 1):
                                v = ws.cell(row=r, column=c).value
                                vv = fmt_val(v)
                                if vv:
                                    vals.append(f"{gl(c)}{r}={vv}")
                                if len(vals) >= MAX_NR_PREVIEW:
                                    break
                            if len(vals) >= MAX_NR_PREVIEW:
                                break
                        preview = "; ".join(vals)
                        if preview:
                            nr_out.append(f"- {dn.name}: {sheet_name}!{ref} = {preview}")
                        else:
                            nr_out.append(f"- {dn.name}: {sheet_name}!{ref}")
                    except Exception:
                        nr_out.append(f"- {dn.name}: {sheet_name}!{ref}")
            if nr_out:
                lines.append("# Named Ranges")
                lines.extend(nr_out)
                lines.append("")
    except Exception:
        pass

    def _emit_key_values(ws: Worksheet, sheet_name: str, min_c, min_r, max_c, max_r):
        lines.append(f"# Sheet: {sheet_name}")
        lines.append("## Key/Values")
        limit_r = _cap_rows(min_r, max_r)
        for r in range(min_r, limit_r + 1):
            k = fmt_val(ws.cell(row=r, column=min_c).value)
            v = fmt_val(ws.cell(row=r, column=min_c + 1).value)
            if not k and not v:
                continue
            if k:
                lines.append(f"- {k}: {v}" if v else f"- {k}:")
        lines.append("")

    def _emit_inferred_table(ws: Worksheet, sheet_name: str, min_c, min_r, max_c, max_r):
        lines.append(f"# Sheet: {sheet_name}")
        lines.append("## Inferred Table")
        lines.append(f"block: {sheet_name}!R{min_r}-{max_r},C{min_c}-{max_c}")
        max_c_eff = min(max_c, min_c + INFER_MAX_COLS - 1)
        max_r_eff = _cap_rows(min_r, max_r)

        headers: List[str] = []
        header_fill = 0
        for c in range(min_c, max_c_eff + 1):
            val = ws.cell(row=min_r, column=c).value
            s = fmt_val("" if val is None else str(val).strip())
            if s:
                header_fill += 1
            headers.append(s)

        fill_ratio = header_fill / max(1, (max_c_eff - min_c + 1))
        if fill_ratio < INFER_MIN_HEADER_FILL and (min_r + 1) <= max_r_eff:
            headers = []
            hdr_r = min_r + 1
            for c in range(min_c, max_c_eff + 1):
                val = ws.cell(row=hdr_r, column=c).value
                s = fmt_val("" if val is None else str(val).strip())
                headers.append(s)
            min_r = hdr_r

        norm_headers = [normalize_header(h) for h in headers]
        rmax = rightmost_nonempty_header(norm_headers)
        if rmax >= 0:
            norm_headers = norm_headers[:rmax + 1]
            max_c_eff = min(max_c_eff, min_c + rmax)

        keep_idx, norm_headers = _keep_and_rename_phantom(norm_headers)
        if any(h for h in norm_headers):
            lines.append("headers: " + ", ".join(h for h in norm_headers if h))

        for r in range(min_r + 1, max_r_eff + 1):
            row_vals: List[str] = []
            for c in range(min_c, max_c_eff + 1):
                vv = ws.cell(row=r, column=c).value
                row_vals.append(fmt_val(vv))
            row_vals = select_indices(row_vals, keep_idx)
            while row_vals and (row_vals[-1] == "" or row_vals[-1] is None):
                row_vals.pop()
            if any(v for v in row_vals):
                lines.append("row: " + ", ".join(row_vals))
        lines.append("")

    for sheet_name in wb_vals.sheetnames:
        ws_v: Worksheet = wb_vals[sheet_name]
        emitted_any = False

        if EMIT_MERGED:
            merges = getattr(ws_v, "merged_cells", None)
            rngs = getattr(merges, "ranges", None) if merges else None
            if rngs:
                lines.append(f"# Sheet: {sheet_name}")
                lines.append("## Merged Ranges")
                for mr in rngs:
                    ref = str(getattr(mr, "coord", getattr(mr, "bounds", mr)))
                    lines.append(f"- {ref}")
                lines.append("")
                emitted_any = True

        if EMIT_CELLS and not emitted_any:
            min_c, min_r, max_c, max_r = _sheet_used_range(ws_v)
            lines.append(f"# Sheet: {sheet_name}")
            lines.append("## Cells (non-empty)")
            emitted = 0
            for r in range(min_r, max_r + 1):
                row_parts: List[str] = []
                for c in range(min_c, max_c + 1):
                    vv = ws_v.cell(row=r, column=c).value
                    if vv is None:
                        continue
                    val_str = fmt_val(vv)
                    if val_str:
                        row_parts.append(val_str if not EMIT_CELL_ADDR else f"{val_str}")
                if row_parts:
                    lines.append("- " + ", ".join(row_parts))
                    emitted += 1
                    if emitted >= MAX_CELLS_PER_SHEET:
                        lines.append("… (cells truncated)")
                        break
            lines.append("")
            emitted_any = True

        if not emitted_any:
            min_c, min_r, max_c, max_r = _sheet_used_range(ws_v)
            max_c = min(max_c, min_c + INFER_MAX_COLS - 1)
            for b_min_c, b_min_r, b_max_c, b_max_r in scan_blocks_by_blank_rows(ws_v, min_c, min_r, max_c, max_r):
                if b_min_r > b_max_r:
                    continue
                if EMIT_KEYVALUES and _detect_key_value(ws_v, b_min_c, b_min_r, b_max_c, b_max_r):
                    _emit_key_values(ws_v, sheet_name, b_min_c, b_min_r, b_max_c, b_max_r)
                else:
                    _emit_inferred_table(ws_v, sheet_name, b_min_c, b_min_r, b_max_c, b_max_r)

    text = "\n".join(line.rstrip() for line in lines if line is not None).strip()
    return (text + "\n" if text else ""), "text/plain"
