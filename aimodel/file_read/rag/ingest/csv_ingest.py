from __future__ import annotations
from typing import Tuple, List
import io, re, csv
from ...core.settings import SETTINGS

def _squeeze_spaces_inline(s: str) -> str:
    return re.sub(r"[ \t]+", " ", (s or "")).strip()

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
        s = str(v).strip()
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

    # read CSV
    txt = io.StringIO(data.decode("utf-8", errors="ignore"))
    sniffer = csv.Sniffer()
    sample = txt.read(2048)
    txt.seek(0)
    dialect = sniffer.sniff(sample) if sample else csv.excel
    reader = csv.reader(txt, dialect)

    lines: List[str] = []
    lines.append("# Sheet: CSV")
    lines.append("## Inferred Table")

    rows = list(reader)
    if not rows:
        return "", "text/plain"

    headers = rows[0][:max_cols]
    norm_headers = [normalize_header(fmt_val(h)) for h in headers]
    if any(norm_headers):
        lines.append("headers: " + ", ".join(norm_headers))

    for r in rows[1:max_rows + 1]:
        vals = [fmt_val(c) for c in r[:max_cols]]
        if any(vals):
            lines.append("row: " + ", ".join(vals))

    lines.append("")
    return "\n".join(lines).strip() + "\n", "text/plain"
