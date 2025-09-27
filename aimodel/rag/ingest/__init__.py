# aimodel/file_read/rag/ingest/__init__.py

from __future__ import annotations

from ...core.logging import get_logger

log = get_logger(__name__)
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Dict, List, Optional, Tuple

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from ...core.settings import SETTINGS
from .common import Chunk, _strip_html, _utf8, build_metas, chunk_text
from .csv_ingest import extract_csv
from .doc_binary_ingest import extract_doc_binary
from .docx_ingest import extract_docx
from .excel_ingest import extract_excel
from .excel_ingest_core import (rightmost_nonempty_header,
                                scan_blocks_by_blank_rows, select_indices)
from .main import sniff_and_extract
from .ocr import is_bad_text, ocr_image_bytes, ocr_pdf
from .pdf_ingest import extract_pdf
from .ppt_ingest import extract_ppt, extract_pptx
from .xls_ingest import extract_xls

__all__ = [
    "SETTINGS",
    "Chunk",
    "Dict",
    "Image",
    "List",
    "Optional",
    "Tuple",
    "_strip_html",
    "_utf8",
    "build_metas",
    "chunk_text",
    "csv",
    "dataclass",
    "date",
    "datetime",
    "extract_csv",
    "extract_doc_binary",
    "extract_docx",
    "extract_excel",
    "extract_pdf",
    "extract_ppt",
    "extract_pptx",
    "extract_xls",
    "hashlib",
    "io",
    "is_bad_text",
    "json",
    "ocr_image_bytes",
    "ocr_pdf",
    "pdfium",
    "pytesseract",
    "re",
    "rightmost_nonempty_header",
    "scan_blocks_by_blank_rows",
    "select_indices",
    "sniff_and_extract",
    "time",
]
