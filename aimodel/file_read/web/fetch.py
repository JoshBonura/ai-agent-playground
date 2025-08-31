# aimodel/file_read/web/fetch.py
from __future__ import annotations
import asyncio
from typing import Tuple, List, Optional, Dict, Any
import time
import httpx

try:
    from readability import Document
except Exception:
    Document = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

try:
    from selectolax.parser import HTMLParser
except Exception:
    HTMLParser = None  # type: ignore

from ..core.settings import SETTINGS


def _req(key: str):
    return SETTINGS[key]

def _ua() -> str:
    return str(_req("web_fetch_user_agent"))

def _timeout() -> float:
    return float(_req("web_fetch_timeout_sec"))

def _max_chars() -> int:
    return int(_req("web_fetch_max_chars"))

def _max_bytes() -> int:
    return int(_req("web_fetch_max_bytes"))

def _max_parallel() -> int:
    return max(1, int(_req("web_fetch_max_parallel")))


async def _read_capped_bytes(resp: httpx.Response, cap_bytes: int) -> bytes:
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
    html = raw_html or ""
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
        except Exception:
            pass
    if HTMLParser is not None:
        try:
            tree = HTMLParser(html)
            for bad in ("script", "style", "noscript"):
                for n in tree.tags(bad):
                    n.decompose()
            txt = tree.body.text(separator=" ", strip=True) if tree.body else tree.text(separator=" ", strip=True)
            if txt:
                return txt
        except Exception:
            pass
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
            for s in soup(["script", "style", "noscript"]):
                s.extract()
            txt = soup.get_text(" ", strip=True)
            if txt:
                return txt
        except Exception:
            pass
    return html


async def fetch_clean(
    url: str,
    timeout_s: Optional[float] = None,
    max_chars: Optional[int] = None,
    max_bytes: Optional[int] = None,
    telemetry: Optional[Dict[str, Any]] = None,
) -> Tuple[str, int, str]:
    t0 = time.perf_counter()
    timeout = _timeout() if timeout_s is None else float(timeout_s)
    cap_chars = _max_chars() if max_chars is None else int(max_chars)
    cap_bytes = _max_bytes() if max_bytes is None else int(max_bytes)

    headers = {"User-Agent": _ua()}
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        raw_bytes = await _read_capped_bytes(r, cap_bytes)
        enc = r.encoding or "utf-8"
        raw_text = raw_bytes.decode(enc, errors="ignore")
        txt = _extract_text_from_html(raw_text, str(r.url))
        txt = (txt or "").strip().replace("\r", "")
        if len(txt) > cap_chars:
            txt = txt[:cap_chars]
        if telemetry is not None:
            telemetry.update({
                "reqUrl": url,
                "finalUrl": str(r.url),
                "status": int(r.status_code),
                "elapsedSec": round(time.perf_counter() - t0, 6),
                "bytes": len(raw_bytes),
                "chars": len(txt),
                "timeoutSec": timeout,
                "capBytes": cap_bytes,
                "capChars": cap_chars,
            })
        return (str(r.url), r.status_code, txt)


async def fetch_many(
    urls: List[str],
    per_timeout_s: Optional[float] = None,
    cap_chars: Optional[int] = None,
    cap_bytes: Optional[int] = None,
    max_parallel: Optional[int] = None,
    telemetry: Optional[Dict[str, Any]] = None,
):
    t_total0 = time.perf_counter()
    sem = asyncio.Semaphore(_max_parallel() if max_parallel is None else int(max_parallel))
    tel_items: List[Dict[str, Any]] = []

    async def _one(u: str):
        item_tel: Dict[str, Any] = {"reqUrl": u}
        t0 = time.perf_counter()
        async with sem:
            try:
                res = await fetch_clean(
                    u,
                    timeout_s=per_timeout_s,
                    max_chars=cap_chars,
                    max_bytes=cap_bytes,
                    telemetry=item_tel,
                )
                item_tel.setdefault("elapsedSec", round(time.perf_counter() - t0, 6))
                item_tel["ok"] = True
                tel_items.append(item_tel)
                return u, res
            except Exception as e:
                item_tel.update({
                    "ok": False,
                    "errorType": type(e).__name__,
                    "errorMsg": str(e),
                    "elapsedSec": round(time.perf_counter() - t0, 6),
                    "timeoutSec": (float(per_timeout_s) if per_timeout_s is not None else _timeout()),
                    "capBytes": (int(cap_bytes) if cap_bytes is not None else _max_bytes()),
                    "capChars": (int(cap_chars) if cap_chars is not None else _max_chars()),
                })
                tel_items.append(item_tel)
                return u, None

    tasks = [_one(u) for u in urls]
    results = await asyncio.gather(*tasks)

    if telemetry is not None:
        ok_cnt = sum(1 for it in tel_items if it.get("ok"))
        telemetry.update({
            "totalSec": round(time.perf_counter() - t_total0, 6),
            "requested": len(urls),
            "ok": ok_cnt,
            "miss": len(urls) - ok_cnt,
            "items": tel_items,
            "settings": {
                "userAgent": _ua(),
                "defaultTimeoutSec": _timeout(),
                "defaultCapChars": _max_chars(),
                "defaultCapBytes": _max_bytes(),
                "maxParallel": _max_parallel() if max_parallel is None else int(max_parallel),
            },
        })

    return results
