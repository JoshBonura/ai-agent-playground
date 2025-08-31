# ===== aimodel/file_read/rag/ingest/__init__.py =====
from __future__ import annotations
from typing import Tuple
import io, json

from .excel_ingest import extract_excel
from .csv_ingest import extract_csv
from .common import _utf8, _strip_html, Chunk, chunk_text, build_metas
from .doc_ingest import extract_docx, extract_doc_binary
from ...core.settings import SETTINGS

__all__ = ["sniff_and_extract", "Chunk", "chunk_text", "build_metas"]

def _ing_dbg(*args):
    try:
        if bool(SETTINGS.effective().get("ingest_debug", False)):
            print("[ingest]", *args)
    except Exception:
        pass

def sniff_and_extract(filename: str, data: bytes) -> Tuple[str, str]:
    name = (filename or "").lower()
    _ing_dbg("route:", name, "bytes=", len(data))

    if name.endswith((".xlsx", ".xlsm")):
        _ing_dbg("-> excel")
        return extract_excel(data)

    if name.endswith((".csv", ".tsv")):
        _ing_dbg("-> csv/tsv")
        return extract_csv(data)

    if name.endswith(".docx"):
        _ing_dbg("-> docx")
        try:
            return extract_docx(data)
        except Exception as e:
            _ing_dbg("docx err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith(".doc"):
        _ing_dbg("-> doc (binary/rtf)")
        try:
            return extract_doc_binary(data)
        except Exception as e:
            _ing_dbg("doc err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith(".rtf"):
        _ing_dbg("-> rtf (via doc_binary)")
        try:
            return extract_doc_binary(data)
        except Exception as e:
            _ing_dbg("rtf err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith(".pdf"):
        _ing_dbg("-> pdf")
        try:
            from pdfminer.high_level import extract_text
            txt = extract_text(io.BytesIO(data)) or ""
            return txt.strip(), "text/plain"
        except Exception as e:
            _ing_dbg("pdfminer err:", repr(e))
            try:
                from PyPDF2 import PdfReader
                r = PdfReader(io.BytesIO(data))
                pages = [(p.extract_text() or "").strip() for p in r.pages]
                return "\n\n".join([p for p in pages if p]).strip(), "text/plain"
            except Exception as e2:
                _ing_dbg("pypdf2 err:", repr(e2))
                return _utf8(data), "text/plain"

    if name.endswith(".json"):
        _ing_dbg("-> json")
        try:
            return json.dumps(json.loads(_utf8(data)), ensure_ascii=False, indent=2), "text/plain"
        except Exception as e:
            _ing_dbg("json err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith((".jsonl", ".jsonlines")):
        _ing_dbg("-> jsonl")
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
        _ing_dbg("-> yaml")
        try:
            import yaml
            obj = yaml.safe_load(_utf8(data))
            return json.dumps(obj, ensure_ascii=False, indent=2), "text/plain"
        except Exception as e:
            _ing_dbg("yaml err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith(".toml"):
        _ing_dbg("-> toml")
        try:
            try:
                import tomllib
                obj = tomllib.loads(_utf8(data))
            except Exception:
                import toml
                obj = toml.loads(_utf8(data))
            return json.dumps(obj, ensure_ascii=False, indent=2), "text/plain"
        except Exception as e:
            _ing_dbg("toml err:", repr(e))
            return _utf8(data), "text/plain"

    if name.endswith((".htm", ".html", ".xml")):
        _ing_dbg("-> html/xml")
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
        _ing_dbg("-> plaintext/code")
        return _utf8(data), "text/plain"

    _ing_dbg("-> default fallback")
    return _utf8(data), "text/plain"
