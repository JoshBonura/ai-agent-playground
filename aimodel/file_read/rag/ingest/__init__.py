from __future__ import annotations
from typing import Tuple
import io, json

from .excel_ingest import extract_excel
from .common import _utf8, _strip_html, Chunk, chunk_text, build_metas

__all__ = ["sniff_and_extract", "Chunk", "chunk_text", "build_metas"]

def sniff_and_extract(filename: str, data: bytes) -> Tuple[str, str]:
    """
    Dispatcher that returns (text, mime) for many file types.
    Excel (.xlsx) is handled by excel_ingest.extract_excel for rich structure.
    """
    name = (filename or "").lower()

    if name.endswith(".xlsx"):
        return extract_excel(data)

    if name.endswith(".docx"):
        try:
            from docx import Document  # python-docx
            doc = Document(io.BytesIO(data))
            paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            return "\n".join(paras).strip(), "text/plain"
        except Exception:
            return _utf8(data), "text/plain"

    if name.endswith(".pdf"):
        try:
            from pdfminer.high_level import extract_text
            txt = extract_text(io.BytesIO(data)) or ""
            return txt.strip(), "text/plain"
        except Exception:
            try:
                from PyPDF2 import PdfReader
                r = PdfReader(io.BytesIO(data))
                pages = [(p.extract_text() or "").strip() for p in r.pages]
                return "\n\n".join([p for p in pages if p]).strip(), "text/plain"
            except Exception:
                return _utf8(data), "text/plain"

    if name.endswith(".json"):
        try:
            return json.dumps(json.loads(_utf8(data)), ensure_ascii=False, indent=2), "text/plain"
        except Exception:
            return _utf8(data), "text/plain"

    if name.endswith((".jsonl", ".jsonlines")):
        lines = _utf8(data).splitlines()
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.dumps(json.loads(ln), ensure_ascii=False, indent=2))
            except Exception:
                out.append(ln)
        return "\n".join(out).strip(), "text/plain"

    if name.endswith((".yaml", ".yml")):
        try:
            import yaml
            obj = yaml.safe_load(_utf8(data))
            return json.dumps(obj, ensure_ascii=False, indent=2), "text/plain"
        except Exception:
            return _utf8(data), "text/plain"

    if name.endswith(".toml"):
        try:
            try:
                import tomllib
                obj = tomllib.loads(_utf8(data))
            except Exception:
                import toml
                obj = toml.loads(_utf8(data))
            return json.dumps(obj, ensure_ascii=False, indent=2), "text/plain"
        except Exception:
            return _utf8(data), "text/plain"

    if name.endswith((".csv", ".tsv")):
        return _utf8(data), "text/plain"

    if name.endswith((".htm", ".html", ".xml")):
        return _strip_html(_utf8(data)), "text/plain"

    # plaintext / code-ish
    if name.endswith((
        ".txt", ".log", ".md",
        ".c", ".cpp", ".h", ".hpp",
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".sh", ".ps1",
        ".rs", ".java", ".go", ".rb", ".php",
        ".swift", ".kt", ".scala", ".lua", ".perl",
    )):
        return _utf8(data), "text/plain"

    # default
    return _utf8(data), "text/plain"
