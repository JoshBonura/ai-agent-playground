# aimodel/file_read/rag/ingest/__init__.py
from __future__ import annotations
from typing import Tuple
import io, json
from .xls_ingest import extract_xls
from .excel_ingest import extract_excel
from .csv_ingest import extract_csv
from .common import _utf8, _strip_html, Chunk, chunk_text, build_metas
from .docx_ingest import extract_docx
from .doc_binary_ingest import extract_doc_binary
from .ppt_ingest import extract_pptx, extract_ppt
from .pdf_ingest import extract_pdf   # <-- new
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

    if name.endswith((".pptx", ".pptm")):
        _ing_dbg("-> pptx/pptm")
        return extract_pptx(data)

    if name.endswith(".ppt"):
        _ing_dbg("-> ppt (ole)")
        return extract_ppt(data)

    if name.endswith((".xlsx", ".xlsm")):
        _ing_dbg("-> excel")
        return extract_excel(data)

    if name.endswith(".xls"):
        _ing_dbg("-> excel (xls via xlrd)")
        return extract_xls(data)

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
        _ing_dbg("-> pdf (delegating to extract_pdf)")
        print("[ingest] call extract_pdf()", flush=True)  # unconditional marker
        from .pdf_ingest import extract_pdf
        return extract_pdf(data)

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
