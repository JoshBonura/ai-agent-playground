from __future__ import annotations

from ...core.logging import get_logger

log = get_logger(__name__)
import io
import re

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from ...core.settings import SETTINGS

_cmd = str(SETTINGS.effective().get("tesseract_cmd", "")).strip()
if _cmd:
    pytesseract.pytesseract.tesseract_cmd = _cmd
_ALNUM = re.compile("[A-Za-z0-9]")


def _alnum_ratio(s: str) -> float:
    if not s:
        return 0.0
    a = len(_ALNUM.findall(s))
    return a / max(1, len(s))


def is_bad_text(s: str) -> bool:
    S = SETTINGS.effective
    min_len = int(S().get("ocr_min_chars_for_ok", 32))
    min_ratio = float(S().get("ocr_min_alnum_ratio_for_ok", 0.15))
    s = (s or "").strip()
    return len(s) < min_len or _alnum_ratio(s) < min_ratio


def ocr_image_bytes(img_bytes: bytes) -> str:
    S = SETTINGS.effective
    lang = str(S().get("ocr_lang", "eng"))
    psm = str(S().get("ocr_psm", "3"))
    oem = str(S().get("ocr_oem", "3"))
    cfg = f"--oem {oem} --psm {psm}"
    with Image.open(io.BytesIO(img_bytes)) as im:
        im = im.convert("L")
        return pytesseract.image_to_string(im, lang=lang, config=cfg) or ""


def ocr_pdf(data: bytes) -> str:
    S = SETTINGS.effective
    dpi = int(S().get("pdf_ocr_dpi", 300))
    max_pages = int(S().get("pdf_ocr_max_pages", 0))
    lang = str(S().get("ocr_lang", "eng"))
    oem = str(S().get("ocr_oem", "3"))
    psm_default = str(S().get("ocr_psm", "6"))
    try_psm = [psm_default, "4", "7", "3"]
    min_side = 1200

    def _dbg(*args):
        try:
            if bool(S().get("ingest_debug", False)):
                log.debug("[ocr_pdf]", *args)
        except Exception:
            pass

    try:
        doc = pdfium.PdfDocument(io.BytesIO(data))
    except Exception as e:
        _dbg("PdfDocument ERROR:", repr(e))
        return ""
    n = len(doc)
    limit = n if max_pages <= 0 else min(n, max_pages)
    _dbg(f"pages={n}", f"limit={limit}", f"dpi={dpi}", f"lang={lang}", f"psm_default={psm_default}")
    out: list[str] = []
    for i in range(limit):
        try:
            page = doc[i]
            pil = page.render(scale=dpi / 72, rotation=0).to_pil().convert("L")
            base_w, base_h = (pil.width, pil.height)
            variants = []
            img1 = pil
            if min(base_w, base_h) < min_side:
                f = max(1.0, min_side / float(min(base_w, base_h)))
                img1 = pil.resize((int(base_w * f), int(base_h * f)))
            variants.append(("gray", img1))
            img2 = img1.point(lambda x: 255 if x > 180 else 0)
            variants.append(("bin180", img2))
            img3 = img1.point(lambda x: 255 - x)
            variants.append(("inv", img3))
            got = ""
            for tag, imgv in variants:
                for psm in try_psm:
                    cfg = f"--oem {oem} --psm {psm}"
                    txt = pytesseract.image_to_string(imgv, lang=lang, config=cfg) or ""
                    txt = txt.strip()
                    _dbg(
                        f"page={i + 1}/{limit}",
                        f"{tag} {imgv.width}x{imgv.height}",
                        f"psm={psm}",
                        f"len={len(txt)}",
                        f"prev={txt[:80]!r}",
                    )
                    if txt:
                        got = txt
                        break
                if got:
                    break
            if got:
                out.append(got)
        except Exception as e:
            _dbg(f"page={i + 1} ERROR:", repr(e))
    final = "\n\n".join(out).strip()
    _dbg("final_len=", len(final))
    return final
