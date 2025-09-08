# aimodel/file_read/web/fetch.py
from __future__ import annotations
import asyncio
from typing import Tuple, List, Optional, Dict, Any
import time
import httpx
from urllib.parse import urlparse

try:
    from readability import Document
except Exception:
    Document = None  # optional

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # optional

try:
    from selectolax.parser import HTMLParser
except Exception:
    HTMLParser = None  # optional

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


# -------------------- Adaptive cooldown (generic, no host hardcoding) --------------------
# host -> (fail_count, cooldown_until_ts)
_BAD_HOSTS: Dict[str, Tuple[int, float]] = {}

def _now() -> float:
    return time.time()

def _host_of(u: str) -> str:
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""

def _cooldown_secs(fails: int) -> float:
    # 15m, 30m, 60m, ... capped at 24h
    base = 15 * 60.0
    cap = 24 * 60 * 60.0
    return min(cap, base * (2 ** max(0, fails - 1)))

def _mark_bad(host: str) -> None:
    if not host:
        return
    fails, until = _BAD_HOSTS.get(host, (0, 0.0))
    fails += 1
    _BAD_HOSTS[host] = (fails, _now() + _cooldown_secs(fails))

def _mark_good(host: str) -> None:
    if not host:
        return
    if host in _BAD_HOSTS:
        fails, until = _BAD_HOSTS[host]
        fails = max(0, fails - 1)
        if fails == 0:
            _BAD_HOSTS.pop(host, None)
        else:
            _BAD_HOSTS[host] = (fails, _now() + _cooldown_secs(fails))

def _is_on_cooldown(host: str) -> bool:
    ent = _BAD_HOSTS.get(host)
    return bool(ent and ent[1] > _now())
# ----------------------------------------------------------------------------------------


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
    # Try readability first (often best for article-like pages)
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
    # Try selectolax (fast, robust)
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
    # Fallback to BeautifulSoup full parse
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
    # Last resort: return raw html (will be trimmed by char cap)
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
        ctype = (r.headers.get("content-type") or "").lower()

        raw_bytes = await _read_capped_bytes(r, cap_bytes)
        enc = r.encoding or "utf-8"
        raw_text = raw_bytes.decode(enc, errors="ignore")
        txt = _extract_text_from_html(raw_text, str(r.url))
        txt = (txt or "").strip().replace("\r", "")
        if len(txt) > cap_chars:
            txt = txt[:cap_chars]

        # Generic usefulness test: skip non-HTML or extremely short bodies
        MIN_USEFUL_CHARS = 80
        host_final = _host_of(str(r.url))
        if ("text/html" not in ctype) or (len(txt) < MIN_USEFUL_CHARS):
            _mark_bad(host_final)
        else:
            _mark_good(host_final)

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
                "contentType": ctype,
                "cooldownFails": _BAD_HOSTS.get(host_final, (0, 0.0))[0] if host_final in _BAD_HOSTS else 0,
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
        host = _host_of(u)

        # Skip hosts currently on adaptive cooldown (generic, no lists)
        if _is_on_cooldown(host):
            item_tel.update({
                "ok": False,
                "skipped": True,
                "skipReason": "cooldown",
                "host": host,
            })
            tel_items.append(item_tel)
            return u, None

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
                item_tel["host"] = host
                tel_items.append(item_tel)
                return u, res
            except Exception as e:
                _mark_bad(host)  # network/HTTP error counts as a fail
                item_tel.update({
                    "ok": False,
                    "errorType": type(e).__name__,
                    "errorMsg": str(e),
                    "elapsedSec": round(time.perf_counter() - t0, 6),
                    "timeoutSec": (float(per_timeout_s) if per_timeout_s is not None else _timeout()),
                    "capBytes": (int(cap_bytes) if cap_bytes is not None else _max_bytes()),
                    "capChars": (int(cap_chars) if cap_chars is not None else _max_chars()),
                    "host": host,
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
