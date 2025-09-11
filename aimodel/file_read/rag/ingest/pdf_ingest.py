from __future__ import annotations

from ...core.logging import get_logger

log = get_logger(__name__)
import io

from ...core.settings import SETTINGS
from .common import _utf8
from .ocr import is_bad_text, ocr_pdf


def _dbg(*args):
    try:
        if bool(SETTINGS.effective().get("ingest_debug", False)):
            log.debug("[pdf_ingest]", *args)
    except Exception:
        pass


def extract_pdf(data: bytes) -> tuple[str, str]:
    log.debug("[pdf_ingest] ENTER extract_pdf")
    S = SETTINGS.effective
    OCR_ENABLED = bool(S().get("pdf_ocr_enable", False))
    OCR_MODE = str(S().get("pdf_ocr_mode", "auto")).lower()
    WHEN_BAD = bool(S().get("pdf_ocr_when_bad", True))
    DPI = int(S().get("pdf_ocr_dpi", 300))
    MAX_PAGES = int(S().get("pdf_ocr_max_pages", 0))
    log.debug(
        f"[pdf_ingest] cfg ocr_enabled={OCR_ENABLED} mode={OCR_MODE} when_bad={WHEN_BAD} dpi={DPI} max_pages={MAX_PAGES}"
    )

    def _do_ocr() -> str:
        log.debug("[pdf_ingest] OCR_CALL begin")
        txt = (ocr_pdf(data) or "").strip()
        log.debug(f"[pdf_ingest] OCR_CALL end text_len={len(txt)} preview={txt[:120]!r}")
        return txt

    if OCR_ENABLED and OCR_MODE == "force":
        _dbg("mode=force -> OCR first")
        ocr_txt = _do_ocr()
        if ocr_txt:
            log.debug("[pdf_ingest] EXIT (force OCR success)")
            return (ocr_txt, "text/plain")
        _dbg("mode=force -> OCR empty, trying text extract")
    txt = ""
    try:
        from pdfminer.high_level import extract_text

        txt = (extract_text(io.BytesIO(data)) or "").strip()
        log.debug(f"[pdf_ingest] pdfminer text_len={len(txt)} preview={txt[:120]!r}")
    except Exception as e:
        log.error(f"[pdf_ingest] pdfminer ERROR {e!r}")
        txt = ""
    if OCR_ENABLED and OCR_MODE != "never":
        try_ocr = not txt or (WHEN_BAD and is_bad_text(txt))
        log.debug(
            f"[pdf_ingest] auto-eval try_ocr={try_ocr} has_text={bool(txt)} is_bad={(is_bad_text(txt) if txt else 'n/a')}"
        )
        if try_ocr:
            ocr_txt = _do_ocr()
            if ocr_txt:
                log.debug("[pdf_ingest] EXIT (auto OCR success)")
                return (ocr_txt, "text/plain")
    if not txt:
        try:
            from PyPDF2 import PdfReader

            r = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "").strip() for p in r.pages]
            txt = "\n\n".join([p for p in pages if p]).strip()
            log.debug(f"[pdf_ingest] pypdf2 text_len={len(txt)} preview={(txt or '')[:120]!r}")
        except Exception as e2:
            log.error(f"[pdf_ingest] pypdf2 ERROR {e2!r}")
            txt = _utf8(data)
            log.debug(f"[pdf_ingest] bytes-fallback text_len={len(txt)}")
    final = txt.strip() if txt else ""
    log.debug(f"[pdf_ingest] EXIT (returned_len={len(final)})")
    return (final, "text/plain")
