# aimodel/file_read/rag/ingest/__init__.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import io, re, csv, hashlib, json
from datetime import datetime, date, time

import pytesseract
from PIL import Image
import pypdfium2 as pdfium

from ...core.settings import SETTINGS

from .ocr import ocr_image_bytes, is_bad_text, ocr_pdf
from .common import _utf8, _strip_html, Chunk, chunk_text, build_metas
from .excel_ingest_core import (
    scan_blocks_by_blank_rows,
    rightmost_nonempty_header,
    select_indices,
)
from .xls_ingest import extract_xls
from .excel_ingest import extract_excel
from .csv_ingest import extract_csv
from .docx_ingest import extract_docx
from .doc_binary_ingest import extract_doc_binary
from .ppt_ingest import extract_pptx, extract_ppt
from .pdf_ingest import extract_pdf
from .main import sniff_and_extract

__all__ = [
    "dataclass",
    "List", "Dict", "Optional", "Tuple",
    "io", "re", "csv", "hashlib", "json",
    "datetime", "date", "time",
    "pytesseract", "Image", "pdfium",
    "SETTINGS",
    "ocr_image_bytes", "is_bad_text", "ocr_pdf",
    "_utf8", "_strip_html", "Chunk", "chunk_text", "build_metas",
    "scan_blocks_by_blank_rows", "rightmost_nonempty_header", "select_indices",
    "extract_xls", "extract_excel", "extract_csv",
    "extract_docx", "extract_doc_binary", "extract_pptx", "extract_ppt", "extract_pdf",
    "sniff_and_extract",
]
