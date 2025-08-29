# aimodel/file_read/web/fetch.py
from __future__ import annotations
import asyncio
from typing import Tuple, List, Optional
import httpx

# Optional extractors (use whatever is installed)
try:
    from readability import Document  # readability-lxml
except Exception:
    Document = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # beautifulsoup4 + lxml
except Exception:
    BeautifulSoup = None  # type: ignore

try:
    from selectolax.parser import HTMLParser  # selectolax
except Exception:
    HTMLParser = None  # type: ignore

from ..core.settings import SETTINGS


def _ua() -> str:
    return str(SETTINGS.get("web_fetch_user_agent", "LocalAI/0.1 (+clean-fetch)"))

def _timeout() -> float:
    try:
        return float(SETTINGS.get("web_fetch_timeout_sec", 8.0))
    except Exception:
        return 8.0

def _max_chars() -> int:
    try:
        return int(SETTINGS.get("web_fetch_max_chars", 3000))
    except Exception:
        return 3000

def _max_bytes() -> int:
    try:
        return int(SETTINGS.get("web_fetch_max_bytes", 1_048_576))
    except Exception:
        return 1_048_576

def _max_parallel() -> int:
    try:
        return max(1, int(SETTINGS.get("web_fetch_max_parallel", 3)))
    except Exception:
        return 3


async def _read_capped_bytes(resp: httpx.Response, cap_bytes: int) -> bytes:
    # Stream and cap to avoid huge downloads
    out = bytearray()
    async for chunk in resp.aiter_bytes():
        if not chunk:
            continue
        remaining = cap_bytes - len(out)
        if remaining <= 0:
            break
        out.extend(chunk[:remaining])
        if len(out) >= cap_bytes:
            break
    return bytes(out)


def _extract_text_from_html(raw_html: str, url: str) -> str:
    """
    Best-effort HTML → text:
      1) readability-lxml (if available): main-article extraction
      2) selectolax (if available): fast DOM text
      3) BeautifulSoup (if available): generic text fallback
      4) Raw text as last resort
    """
    html = raw_html or ""

    # 1) readability main content
    if Document is not None:
        try:
            doc = Document(html)
            summary_html = doc.summary(html_partial=True) or ""
            if summary_html:
                if BeautifulSoup is not None:
                    soup = BeautifulSoup(summary_html, "lxml")
                    txt = soup.get_text(" ", strip=True)
                    if txt:
                        return txt
                # If bs4 missing, fall back to selectolax/plain below
        except Exception:
            pass

    # 2) selectolax full text
    if HTMLParser is not None:
        try:
            tree = HTMLParser(html)
            # Remove script/style/noscript quickly if present
            for bad in ("script", "style", "noscript"):
                for n in tree.tags(bad):
                    n.decompose()
            txt = tree.body.text(separator=" ", strip=True) if tree.body else tree.text(separator=" ", strip=True)
            if txt:
                return txt
        except Exception:
            pass

    # 3) BeautifulSoup full text
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
            # Strip scripts/styles
            for s in soup(["script", "style", "noscript"]):
                s.extract()
            txt = soup.get_text(" ", strip=True)
            if txt:
                return txt
        except Exception:
            pass

    # 4) Raw (no HTML parsing available)
    return html


async def fetch_clean(
    url: str,
    timeout_s: Optional[float] = None,
    max_chars: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Tuple[str, int, str]:
    """
    Returns: (final_url, status_code, cleaned_text)
    - cleaned_text is extracted via readability/selectolax/bs4 if available; else raw
    - caps by bytes first, then by chars
    """
    timeout = _timeout() if timeout_s is None else float(timeout_s)
    cap_chars = _max_chars() if max_chars is None else int(max_chars)
    cap_bytes = _max_bytes() if max_bytes is None else int(max_bytes)

    headers = {"User-Agent": _ua()}
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()

        # Stream with byte cap
        raw_bytes = await _read_capped_bytes(r, cap_bytes)
        # Text decode with fallback (httpx sets encoding heuristically)
        enc = r.encoding or "utf-8"
        raw_text = raw_bytes.decode(enc, errors="ignore")

        # Extract/clean HTML to text (no trafilatura)
        txt = _extract_text_from_html(raw_text, str(r.url))
        txt = (txt or "").strip().replace("\r", "")

        if len(txt) > cap_chars:
            txt = txt[:cap_chars]

        return (str(r.url), r.status_code, txt)


async def fetch_many(
    urls: List[str],
    per_timeout_s: Optional[float] = None,
    cap_chars: Optional[int] = None,
    cap_bytes: Optional[int] = None,
    max_parallel: Optional[int] = None,
):
    sem = asyncio.Semaphore(_max_parallel() if max_parallel is None else int(max_parallel))

    async def _one(u: str):
        async with sem:
            try:
                return u, await fetch_clean(
                    u,
                    timeout_s=per_timeout_s,
                    max_chars=cap_chars,
                    max_bytes=cap_bytes,
                )
            except Exception:
                return u, None

    tasks = [_one(u) for u in urls]
    return await asyncio.gather(*tasks)
