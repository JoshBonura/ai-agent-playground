# ===== aimodel/file_read/rag/ingest/common.py =====
from __future__ import annotations

from ...core.logging import get_logger

log = get_logger(__name__)
import re
from dataclasses import dataclass

from ...core.settings import SETTINGS


@dataclass
class Chunk:
    text: str
    meta: dict[str, str]


def _utf8(data: bytes) -> str:
    return (data or b"").decode("utf-8", errors="ignore")


def _strip_html(txt: str) -> str:
    if not txt:
        return ""

    txt = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", txt)
    txt = re.sub(r"(?is)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?is)</p>", "\n\n", txt)
    txt = re.sub(r"(?is)<.*?>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


_HDR_RE = re.compile(r"^(#{1,3})\s+.*$", flags=re.MULTILINE)
_PARA_SPLIT_RE = re.compile(r"\n\s*\n+")


def _split_sections(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    starts = [m.start() for m in _HDR_RE.finditer(text)]
    if not starts:
        return [text]
    if 0 not in starts:
        starts = [0] + starts
    sections: list[str] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[s:e].strip()
        if block:
            sections.append(block)
    return sections


def _split_paragraphs(block: str) -> list[str]:
    paras = [p.strip() for p in _PARA_SPLIT_RE.split(block or "")]
    return [p for p in paras if p]


def _hard_split(text: str, max_len: int) -> list[str]:
    approx = re.split(r"(?<=[\.\!\?\;])\s+", text or "")
    out: list[str] = []
    buf = ""
    for s in approx:
        if not s:
            continue
        if len(buf) + (1 if buf else 0) + len(s) <= max_len:
            buf = s if not buf else (buf + " " + s)
        else:
            if buf:
                out.append(buf)
            if len(s) <= max_len:
                out.append(s)
            else:
                words = re.split(r"\s+", s)
                cur = ""
                for w in words:
                    if not w:
                        continue
                    if len(cur) + (1 if cur else 0) + len(w) <= max_len:
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


def _pack_with_budget(pieces: list[str], *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in pieces:
        plen = len(p)
        if plen > max_chars:
            chunks.extend(_hard_split(p, max_chars))
            continue
        if cur_len == 0:
            cur, cur_len = [p], plen
            continue
        if cur_len + 2 + plen <= max_chars:
            cur.append(p)
            cur_len += 2 + plen
        else:
            chunks.append("\n\n".join(cur).strip())
            cur, cur_len = [p], plen
    if cur_len:
        chunks.append("\n\n".join(cur).strip())
    return chunks


def chunk_text(
    text: str,
    meta: dict[str, str] | None = None,
    *,
    max_chars: int = int(SETTINGS.get("rag_max_chars_per_chunk", 800)),
    overlap: int = int(SETTINGS.get("rag_chunk_overlap_chars", 150)),
) -> list[Chunk]:
    base_meta = (meta or {}).copy()
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= max_chars:
        return [Chunk(text=text, meta=base_meta)]

    sections = _split_sections(text)
    if not sections:
        sections = [text]

    chunks: list[Chunk] = []
    last_tail: str | None = None

    for sec in sections:
        paras = _split_paragraphs(sec)
        if not paras:
            continue
        packed = _pack_with_budget(paras, max_chars=max_chars)
        for ch in packed:
            if last_tail and overlap > 0:
                tail = last_tail[-overlap:] if len(last_tail) > overlap else last_tail
                candidate = f"{tail}\n{ch}"
                chunks.append(
                    Chunk(text=candidate if len(candidate) <= max_chars else ch, meta=base_meta)
                )
            else:
                chunks.append(Chunk(text=ch, meta=base_meta))
            last_tail = ch

    return chunks


def build_metas(
    session_id: str | None, filename: str, chunks: list[Chunk], *, size: int = 0
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for i, c in enumerate(chunks):
        out.append(
            {
                "id": f"{filename}:{i}",
                "sessionId": session_id or "",
                "source": filename,
                "title": filename,
                "mime": "text/plain",
                "size": str(size),
                "chunkIndex": str(i),
                "text": c.text,
            }
        )
    return out
