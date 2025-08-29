from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional
import re
from ...core.settings import SETTINGS

@dataclass
class Chunk:
    text: str
    meta: Dict[str, str]

def _utf8(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")

def _strip_html(txt: str) -> str:
    txt = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", txt)
    txt = re.sub(r"(?is)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?is)</p>", "\n\n", txt)
    txt = re.sub(r"(?is)<.*?>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()

_WHITESPACE_RE = re.compile(r"\s+")
_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")

def _split_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in _PARA_SPLIT_RE.split(text)]
    return [p for p in paras if p]

def _split_hard(text: str, max_len: int) -> List[str]:
    approx = re.split(r"(?<=[\.\!\?\;])\s+", text)
    out: List[str] = []
    buf = ""
    for s in approx:
        if not s:
            continue
        if len(buf) + 1 + len(s) <= max_len:
            buf = s if not buf else (buf + " " + s)
        else:
            if buf:
                out.append(buf)
            if len(s) <= max_len:
                out.append(s)
            else:
                words = _WHITESPACE_RE.split(s)
                cur = ""
                for w in words:
                    if not w:
                        continue
                    if len(cur) + 1 + len(w) <= max_len:
                        cur = w if not cur else (cur + " " + w)
                    else:
                        if cur:
                            out.append(cur)
                        cur = w
                if cur:
                    out.append(cur)
            buf = ""
    if buf:
        out.append(buf)
    return out

def chunk_text(
    text: str,
    meta: Optional[Dict[str, str]] = None,
    *,
    max_chars=int(SETTINGS.get("rag_max_chars_per_chunk", 800)),
    overlap=int(SETTINGS.get("rag_chunk_overlap_chars", 150)),
) -> List[Chunk]:
    meta = meta or {}
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_chars:
        return [Chunk(text=text, meta=meta.copy())]

    paragraphs = _split_paragraphs(text) or [text]

    normalized: List[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            normalized.append(p)
        else:
            normalized.extend(_split_hard(p, max_chars))

    chunks: List[Chunk] = []
    cur: List[str] = []
    cur_len = 0

    for piece in normalized:
        plen = len(piece)
        if cur_len == 0:
            cur, cur_len = [piece], plen
            continue
        if cur_len + 1 + plen <= max_chars:
            cur.append(piece)
            cur_len += 1 + plen
        else:
            joined = "\n".join(cur).strip()
            if joined:
                chunks.append(Chunk(text=joined, meta=meta.copy()))
            if overlap > 0 and joined:
                tail = joined[-overlap:]
                cur, cur_len = [tail, piece], len(tail) + 1 + plen
            else:
                cur, cur_len = [piece], plen

    if cur_len:
        joined = "\n".join(cur).strip()
        if joined:
            chunks.append(Chunk(text=joined, meta=meta.copy()))

    return chunks

def build_metas(session_id: Optional[str], filename: str, chunks: List[Chunk], *, size: int = 0) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for i, c in enumerate(chunks):
        out.append({
            "id": f"{filename}:{i}",
            "sessionId": session_id or "",
            "source": filename,
            "title": filename,
            "mime": "text/plain",
            "size": str(size),
            "chunkIndex": str(i),
            "text": c.text,  # stored for RAG block display
        })
    return out
