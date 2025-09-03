# aimodel/file_read/rag/ingest/pdf_ingest.py
from __future__ import annotations
from typing import Tuple
import io
from ...core.settings import SETTINGS
from .ocr import is_bad_text, ocr_pdf
from .common import _utf8

def _dbg(*args):
    try:
        if bool(SETTINGS.effective().get("ingest_debug", False)):
            print("[pdf_ingest]", *args, flush=True)
    except Exception:
        pass

def extract_pdf(data: bytes) -> Tuple[str, str]:
    print("[pdf_ingest] ENTER extract_pdf", flush=True)

    S = SETTINGS.effective
    OCR_ENABLED = bool(S().get("pdf_ocr_enable", False))
    OCR_MODE = str(S().get("pdf_ocr_mode", "auto")).lower()   # auto | force | never
    WHEN_BAD  = bool(S().get("pdf_ocr_when_bad", True))
    DPI       = int(S().get("pdf_ocr_dpi", 300))
    MAX_PAGES = int(S().get("pdf_ocr_max_pages", 0))

    # Unconditional config echo so we KNOW what the server is using
    print(f"[pdf_ingest] cfg ocr_enabled={OCR_ENABLED} mode={OCR_MODE} when_bad={WHEN_BAD} dpi={DPI} max_pages={MAX_PAGES}", flush=True)

    def _do_ocr() -> str:
        print("[pdf_ingest] OCR_CALL begin", flush=True)  # <-- undeniable marker
        txt = (ocr_pdf(data) or "").strip()
        print(f"[pdf_ingest] OCR_CALL end text_len={len(txt)} preview={repr(txt[:120])}", flush=True)
        return txt

    # FORCE: run OCR up front
    if OCR_ENABLED and OCR_MODE == "force":
        _dbg("mode=force -> OCR first")
        ocr_txt = _do_ocr()
        if ocr_txt:
            print("[pdf_ingest] EXIT (force OCR success)", flush=True)
            return ocr_txt, "text/plain"
        _dbg("mode=force -> OCR empty, trying text extract")

    # Try embedded text (pdfminer)
    txt = ""
    try:
        from pdfminer.high_level import extract_text
        txt = (extract_text(io.BytesIO(data)) or "").strip()
        print(f"[pdf_ingest] pdfminer text_len={len(txt)} preview={repr(txt[:120])}", flush=True)
    except Exception as e:
        print(f"[pdf_ingest] pdfminer ERROR {repr(e)}", flush=True)
        txt = ""

    # AUTO: OCR if missing/weak text
    if OCR_ENABLED and OCR_MODE != "never":
        try_ocr = (not txt) or (WHEN_BAD and is_bad_text(txt))
        print(f"[pdf_ingest] auto-eval try_ocr={try_ocr} has_text={bool(txt)} is_bad={(is_bad_text(txt) if txt else 'n/a')}", flush=True)
        if try_ocr:
            ocr_txt = _do_ocr()
            if ocr_txt:
                print("[pdf_ingest] EXIT (auto OCR success)", flush=True)
                return ocr_txt, "text/plain"

    # Fallback: PyPDF2
    if not txt:
        try:
            from PyPDF2 import PdfReader
            r = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "").strip() for p in r.pages]
            txt = "\n\n".join([p for p in pages if p]).strip()
            print(f"[pdf_ingest] pypdf2 text_len={len(txt)} preview={repr((txt or '')[:120])}", flush=True)
        except Exception as e2:
            print(f"[pdf_ingest] pypdf2 ERROR {repr(e2)}", flush=True)
            txt = _utf8(data)
            print(f"[pdf_ingest] bytes-fallback text_len={len(txt)}", flush=True)

    final = (txt.strip() if txt else "")
    print(f"[pdf_ingest] EXIT (returned_len={len(final)})", flush=True)
    return final, "text/plain"
