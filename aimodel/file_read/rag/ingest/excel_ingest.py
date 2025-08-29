from __future__ import annotations
from typing import Tuple, List
import io, re
from datetime import datetime, date, time
from ...core.settings import SETTINGS

def S(key: str):
    return SETTINGS.effective()[key]

_WS_RE = re.compile(r"[ \t]+")

def _squeeze_spaces(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()

def extract_excel(data: bytes) -> Tuple[str, str]:
    from openpyxl import load_workbook
    from openpyxl.utils import range_boundaries, get_column_letter
    from openpyxl.worksheet.worksheet import Worksheet

    sig = int(S("excel_number_sigfigs"))
    maxp = int(S("excel_decimal_max_places"))
    trim = bool(S("excel_trim_trailing_zeros"))
    drop_midnight = bool(S("excel_dates_drop_time_if_midnight"))
    time_prec = str(S("excel_time_precision"))
    max_chars = int(S("excel_value_max_chars"))
    quote_strings = bool(S("excel_quote_strings"))

    def clip(s: str) -> str:
        return s if (max_chars <= 0 or len(s) <= max_chars) else s[:max_chars] + "…"

    def fmt_number(v) -> str:
        s = format(float(v), f".{sig}g") if sig > 0 else f"{float(v):.{maxp}f}"
        if "e" in s or "E" in s:
            try:
                s = f"{float(s):.{maxp}f}"
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
        if "\n" in s:
            s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        s = clip(s)
        if quote_strings and re.search(r"[^A-Za-z0-9_.-]", s):
            return f"\"{s}\""
        return s

    wb_vals = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    wb_form = load_workbook(io.BytesIO(data), data_only=False, read_only=True)

    MAX_ROWS_PER_TABLE = int(S("excel_max_rows_per_table"))
    MAX_FORMULAS_PER_SHEET = int(S("excel_max_formulas_per_sheet"))
    MAX_CELLS_PER_SHEET = int(S("excel_max_cells_per_sheet"))
    MAX_NR_PREVIEW = int(S("excel_named_range_preview"))
    EMIT_TABLES = bool(S("excel_emit_tables"))
    EMIT_MERGED = bool(S("excel_emit_merged"))
    EMIT_CELLS = bool(S("excel_emit_cells"))

    lines: List[str] = []

    try:
        if getattr(wb_vals, "defined_names", None):
            nr_out: List[str] = []
            for dn in wb_vals.defined_names.definedName:
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
                        ws_cell = ws.cell
                        gl = get_column_letter
                        for r in range(min_r, max_r + 1):
                            for c in range(min_c, max_c + 1):
                                v = ws_cell(row=r, column=c).value
                                vv = fmt_val(v)
                                if vv:
                                    vals.append(f"{gl(c)}{r}={vv}")
                                if len(vals) >= MAX_NR_PREVIEW:
                                    break
                            if len(vals) >= MAX_NR_PREVIEW:
                                break
                        vals_str = "; ".join(vals)
                        if vals_str:
                            nr_out.append(f"- {dn.name}: {sheet_name}!{ref} = {vals_str}")
                        else:
                            nr_out.append(f"- {dn.name}: {sheet_name}!{ref}")
                    except Exception:
                        nr_out.append(f"- {dn.name}: {sheet_name}!{ref}")
            if nr_out:
                lines.append("## Named Ranges")
                lines.extend(nr_out)
                lines.append("")
    except Exception:
        pass

    col_letter_cache = {}

    for sheet_name in wb_vals.sheetnames:
        ws_v: Worksheet = wb_vals[sheet_name]
        ws_f: Worksheet = wb_form[sheet_name]
        lines.append(f"# Sheet: {sheet_name}")

        formulas_emitted = 0

        if EMIT_TABLES:
            try:
                tables = dict(getattr(ws_v, "tables", {}) or {})
                if tables:
                    lines.append("## Tables")
                    for tname, tobj in tables.items():
                        ref = getattr(tobj, "ref", "")
                        lines.append(f"- Table {tname} ({ref})")
                        try:
                            min_c, min_r, max_c, max_r = range_boundaries(ref)
                        except Exception:
                            min_r = 1; min_c = 1
                            max_r = ws_v.max_row or 1
                            max_c = ws_v.max_column or 1
                        headers: List[str] = []
                        ws_v_cell = ws_v.cell
                        ws_f_cell = ws_f.cell
                        gl = get_column_letter
                        for c in range(min_c, max_c + 1):
                            v = ws_v_cell(row=min_r, column=c).value
                            headers.append(fmt_val("" if v is None else str(v).strip()))
                        if any(h for h in headers):
                            lines.append(f"  headers: [{', '.join(h for h in headers if h)}]")
                        shown = 0
                        for r in range(min_r + 1, max_r + 1):
                            cells: List[str] = []
                            need_formula = formulas_emitted < MAX_FORMULAS_PER_SHEET
                            for c in range(min_c, max_c + 1):
                                cl = col_letter_cache.get(c)
                                if cl is None:
                                    cl = gl(c)
                                    col_letter_cache[c] = cl
                                addr = f"{cl}{r}"
                                vv = ws_v_cell(row=r, column=c).value
                                val_str = fmt_val(vv)
                                fv = ws_f_cell(row=r, column=c).value if need_formula else None
                                if isinstance(fv, str) and fv.startswith("=") and need_formula:
                                    if val_str:
                                        cells.append(f"{addr}={val_str} (formula:={fv[1:]})")
                                    else:
                                        cells.append(f"{addr} (formula:={fv[1:]})")
                                    formulas_emitted += 1
                                    need_formula = formulas_emitted < MAX_FORMULAS_PER_SHEET
                                elif val_str:
                                    cells.append(f"{addr}={val_str}")
                            if not cells:
                                continue
                            lines.append(f"  row {r}: " + ", ".join(cells))
                            shown += 1
                            if shown >= MAX_ROWS_PER_TABLE:
                                lines.append("  - … (rows truncated)")
                                break
                    lines.append("")
            except Exception:
                pass

        if EMIT_MERGED:
            try:
                merges = getattr(ws_v, "merged_cells", None)
                if merges and getattr(merges, "ranges", None):
                    lines.append("## Merged Ranges")
                    for mr in merges.ranges:
                        ref = str(getattr(mr, "coord", getattr(mr, "bounds", mr)))
                        lines.append(f"- {ref}")
                    lines.append("")
            except Exception:
                pass

        if EMIT_CELLS:
            try:
                if callable(getattr(ws_v, "calculate_dimension", None)):
                    dim_ref = ws_v.calculate_dimension()
                    min_c, min_r, max_c, max_r = range_boundaries(dim_ref)
                else:
                    min_r = 1; min_c = 1
                    max_r = ws_v.max_row or 1
                    max_c = ws_v.max_column or 1
                lines.append(f"## Cells (non-empty, first {MAX_CELLS_PER_SHEET})")
                emitted = 0
                ws_v_cell = ws_v.cell
                ws_f_cell = ws_f.cell
                gl = get_column_letter
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        need_formula = formulas_emitted < MAX_FORMULAS_PER_SHEET
                        vv = ws_v_cell(row=r, column=c).value
                        fv = ws_f_cell(row=r, column=c).value if need_formula or vv is None else None
                        if vv is None and not (isinstance(fv, str) and fv and fv.startswith("=")):
                            continue
                        cl = col_letter_cache.get(c)
                        if cl is None:
                            cl = gl(c)
                            col_letter_cache[c] = cl
                        addr = f"{cl}{r}"
                        val_str = fmt_val(vv)
                        if isinstance(fv, str) and fv.startswith("=") and need_formula:
                            if val_str:
                                lines.append(f"- {addr}={val_str} (formula:={fv[1:]})")
                            else:
                                lines.append(f"- {addr} (formula:={fv[1:]})")
                            formulas_emitted += 1
                        else:
                            if val_str:
                                lines.append(f"- {addr}={val_str}")
                            else:
                                continue
                        emitted += 1
                        if emitted >= MAX_CELLS_PER_SHEET:
                            lines.append("… (cells truncated)")
                            break
                    if emitted >= MAX_CELLS_PER_SHEET:
                        break
                lines.append("")
            except Exception:
                lines.append("")

    txt = _squeeze_spaces("\n".join(lines).strip())
    return txt, "text/plain"
