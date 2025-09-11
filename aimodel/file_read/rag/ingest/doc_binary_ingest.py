from __future__ import annotations

from ...core.logging import get_logger

log = get_logger(__name__)
import re

from ...core.settings import SETTINGS

_WS_RE = re.compile("[ \\t]+")


def _squeeze_spaces(s: str) -> str:
    s = (s or "").replace("\xa0", " ")
    s = _WS_RE.sub(" ", s)
    return s.strip()


def _is_ole(b: bytes) -> bool:
    return len(b) >= 8 and b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _dbg(msg: str):
    try:
        S = SETTINGS.effective
        if bool(S().get("doc_debug", False)):
            log.info(f"[doc_ingest] {msg}")
    except Exception:
        pass


_RTF_CTRL_RE = re.compile("\\\\[a-zA-Z]+-?\\d* ?")
_RTF_GROUP_RE = re.compile("[{}]")
_RTF_UNICODE_RE = re.compile("\\\\u(-?\\d+)\\??")
_RTF_HEX_RE = re.compile("\\\\'[0-9a-fA-F]{2}")
_HEX_BLOCK_RE = re.compile("(?:\\s*[0-9A-Fa-f]{2}){120,}")


def _rtf_to_text_simple(data: bytes, *, keep_newlines: bool = True) -> str:
    try:
        s = data.decode("latin-1", errors="ignore")
    except Exception:
        s = data.decode("utf-8", errors="ignore")

    def _hex_sub(m):
        try:
            return bytes.fromhex(m.group(0)[2:]).decode("latin-1", errors="ignore")
        except Exception:
            return ""

    s = _RTF_HEX_RE.sub(_hex_sub, s)

    def _uni_sub(m):
        try:
            cp = int(m.group(1))
            if cp < 0:
                cp = 65536 + cp
            return chr(cp)
        except Exception:
            return ""

    s = _RTF_UNICODE_RE.sub(_uni_sub, s)
    s = s.replace("\\par", "\n").replace("\\line", "\n")
    s = _RTF_CTRL_RE.sub("", s)
    s = _RTF_GROUP_RE.sub("", s)
    s = _HEX_BLOCK_RE.sub("", s)
    s = s.replace("\r", "\n")
    s = re.sub("\\n\\s*\\n\\s*\\n+", "\n\n", s)
    s = _squeeze_spaces(s)
    return s if keep_newlines else s.replace("\n", " ")


def _rtf_to_text_via_lib(data: bytes, *, keep_newlines: bool = True) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
    except Exception:
        return _rtf_to_text_simple(data, keep_newlines=keep_newlines)
    try:
        s = data.decode("latin-1", errors="ignore")
    except Exception:
        s = data.decode("utf-8", errors="ignore")
    try:
        txt = rtf_to_text(s)
    except Exception:
        txt = _rtf_to_text_simple(data, keep_newlines=keep_newlines)
    txt = _squeeze_spaces(txt)
    return txt if keep_newlines else txt.replace("\n", " ")


def _generic_ole_text(data: bytes) -> str:
    S = SETTINGS.effective
    MIN_RUN = int(S().get("doc_ole_min_run_chars", 8))
    MAX_LINE = int(S().get("doc_ole_max_line_chars", 600))
    MIN_ALPHA_RATIO = float(S().get("doc_ole_min_alpha_ratio", 0.25))
    DROP_XMLISH = bool(S().get("doc_ole_drop_xmlish", True))
    DROP_PATHISH = bool(S().get("doc_ole_drop_pathish", True))
    DROP_SYMBOL_LINES = bool(S().get("doc_ole_drop_symbol_lines", True))
    DEDUPE_SHORT_REPEATS = bool(S().get("doc_ole_dedupe_short_repeats", True))
    XMLISH = re.compile("^\\s*<[^>]+>", re.I)
    PATHISH = re.compile("[\\\\/].+\\.(?:xml|rels|png|jpg|jpeg|gif|bmp|bin|dat)\\b", re.I)
    SYMBOLLINE = re.compile("^[\\W_]{6,}$")
    s = data.replace(b"\x00", b"")
    runs = re.findall(b"[\\t\\r\\n\\x20-\\x7E]{%d,}" % MIN_RUN, s)
    if not runs:
        return ""

    def _dec(b: bytes) -> str:
        try:
            return b.decode("cp1252", errors="ignore")
        except Exception:
            return b.decode("latin-1", errors="ignore")

    kept: list[str] = []
    for raw in runs:
        chunk = _dec(raw).replace("\r", "\n")
        for ln in re.split("\\n+", chunk):
            t = ln.strip()
            if not t:
                continue
            if MAX_LINE > 0 and len(t) > MAX_LINE:
                t = t[:MAX_LINE].rstrip()
            t = _squeeze_spaces(t)
            letters = sum(1 for c in t if c.isalpha())
            if letters / max(1, len(t)) < MIN_ALPHA_RATIO:
                continue
            if DROP_XMLISH and XMLISH.search(t):
                continue
            if DROP_PATHISH and PATHISH.search(t):
                continue
            if DROP_SYMBOL_LINES and SYMBOLLINE.fullmatch(t):
                continue
            if DEDUPE_SHORT_REPEATS:
                t = re.sub("\\b(\\w{2,4})\\1{2,}\\b", "\\1\\1", t)
            kept.append(t)
    out = "\n".join(kept)
    out = re.sub("\\n\\s*\\n\\s*\\n+", "\n\n", out).strip()
    return out


def extract_doc_binary(data: bytes) -> tuple[str, str]:
    head = (data[:64] or b"").lstrip()
    is_rtf = head.startswith(b"{\\rtf") or head.startswith(b"{\\RTF}")
    is_ole = _is_ole(data)
    _dbg(f"extract_doc_binary: bytes={len(data)} is_rtf={is_rtf} is_ole={is_ole}")
    if is_rtf:
        txt = _rtf_to_text_via_lib(data, keep_newlines=True).strip()
        return (txt + "\n" if txt else "", "text/plain")
    if is_ole:
        txt = _generic_ole_text(data)
        return (txt + "\n" if txt else "", "text/plain")
    try:
        txt = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        txt = data.decode("latin-1", errors="ignore").strip()
    return (txt + ("\n" if txt else ""), "text/plain")
