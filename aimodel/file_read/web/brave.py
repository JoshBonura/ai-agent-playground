from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
import hashlib
import time
import urllib.parse
from typing import Any

from ..core.http import get_client
from ..core.settings import SETTINGS
from .orchestrator_common import _host
from .provider import SearchHit

_CACHE: dict[str, tuple[float, list[SearchHit]]] = {}


def _cache_key(query: str, base: str, key_marker: str) -> str:
    q = (query or "").strip().lower()
    b = (base or "").strip().lower()
    m = (key_marker or "").strip().lower()
    return f"{q}||{b}||{m}"


def _cache_get(key: str) -> list[SearchHit] | None:
    eff = SETTINGS.effective()
    ttl = int(eff["web_search_cache_ttl_sec"])
    v = _CACHE.get(key)
    if not v:
        return None
    ts, hits = v
    if time.time() - ts > ttl:
        _CACHE.pop(key, None)
        return None
    return hits


def _cache_set(key: str, hits: list[SearchHit]) -> None:
    _CACHE[key] = (time.time(), hits)


def _set_hits_telemetry(
    tel: dict[str, Any], all_hits: list[SearchHit], out: list[SearchHit]
) -> None:
    tel["hits"] = {
        "total": len(all_hits),
        "returned": len(out),
        "top": [f"{h.rank}:{_host(h.url)}:{(h.title or '')[:60]}" for h in out[:5]],
    }


def _build_url(base: str, q: str, k: int) -> str:
    params = {"q": q, "count": str(max(1, k))}
    return f"{base}?{urllib.parse.urlencode(params)}"


def _num(x: Any) -> int | None:
    try:
        return int(str(x))
    except Exception:
        return None


class BraveProvider:
    async def search(
        self,
        query: str,
        k: int = 3,
        telemetry: dict[str, Any] | None = None,
        xid: str | None = None,
    ) -> list[SearchHit]:
        t_start = time.perf_counter()
        eff = SETTINGS.effective()
        q_norm = (query or "").strip()
        if not q_norm:
            if telemetry is not None:
                telemetry.update(
                    {
                        "query": q_norm,
                        "k": int(k),
                        "supersetK": int(k),
                        "elapsedSec": round(time.perf_counter() - t_start, 6),
                        "cache": {"hit": False},
                    }
                )
            return []

        superset_k = max(int(k), int(eff["web_search_cache_superset_k"]))
        tel: dict[str, Any] = {"query": q_norm, "k": int(k), "supersetK": superset_k}

        brave_base = (
            eff.get("brave_api_base") or "https://api.search.brave.com/res/v1/web/search"
        ).strip()
        key = (SETTINGS.get("brave_api_key", "") or "").strip()
        key_hash = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8] if key else "nokey"

        ckey = _cache_key(q_norm, brave_base, key_hash)
        t_cache = time.perf_counter()
        cached = _cache_get(ckey)
        tel["cache"] = {
            "hit": cached is not None,
            "elapsedSec": round(time.perf_counter() - t_cache, 6),
        }
        if cached is not None:
            log.debug(
                "BRAVE cache hit",
                {"query": q_norm, "k": k, "base": brave_base, "keyHash": key_hash},
            )
            out = cached[:k]
            _set_hits_telemetry(tel, cached, out)
            tel["elapsedSec"] = round(time.perf_counter() - t_start, 6)
            if telemetry is not None:
                telemetry.update(tel)
            return out

        hits: list[SearchHit] = []
        prov_info: dict[str, Any] = {"available": True}
        t_fetch = time.perf_counter()

        log.debug("BRAVE cfg", {"base": brave_base, "byok": True, "keyHash": key_hash})
        url = _build_url(brave_base, q_norm, superset_k)
        headers: dict[str, str] = {}
        if key:
            headers["X-Subscription-Token"] = key
        log.debug("BRAVE headers", {"hasKey": bool(key)})

        if not key:
            prov_info["errorType"] = "Unauthorized"
            prov_info["errorMsg"] = "No Brave API key configured in settings"
        else:
            try:
                timeout = float(eff.get("web_fetch_timeout_sec", 8))
                log.debug("BRAVE call", {"url": url, "timeoutSec": timeout})
                client = await get_client()
                r = await client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
                log.debug(
                    "BRAVE resp",
                    {
                        "status": r.status_code,
                        "len": len(r.text or ""),
                        "preview": r.text[:200] if r.text else "",
                    },
                )
                r.raise_for_status()
                data = r.json()

                rate = {
                    "minute": {
                        "limit": _num(r.headers.get("X-RateLimit-Limit-Minute")),
                        "remaining": _num(r.headers.get("X-RateLimit-Remaining-Minute")),
                        "resetMs": _num(r.headers.get("X-RateLimit-Reset-Minute")),
                    },
                    "day": {
                        "limit": _num(r.headers.get("X-RateLimit-Limit-Day")),
                        "remaining": _num(r.headers.get("X-RateLimit-Remaining-Day")),
                        "resetMs": _num(r.headers.get("X-RateLimit-Reset-Day")),
                    },
                }
                prov_info["rate"] = rate

                web = (data or {}).get("web") or {}
                results = web.get("results") or []
                for i, item in enumerate(results[:superset_k], start=1):
                    title = (item.get("title") or "").strip()
                    url_i = (item.get("url") or "").strip()
                    snippet = (item.get("description") or "").strip() or None
                    if not url_i:
                        continue
                    hits.append(SearchHit(title=title or url_i, url=url_i, snippet=snippet, rank=i))

                prov_info["errorType"] = None
                prov_info["errorMsg"] = None

            except Exception as e:
                # Keep your non-fatal provider error path with structured info
                # (We don't raise; we record and return whatever we could gather.)
                # If you'd prefer to fail hard, you could raise ExternalServiceError here.
                log.debug("BRAVE exception", {"type": type(e).__name__, "msg": str(e)})
                prov_info["errorType"] = type(e).__name__
                prov_info["errorMsg"] = str(e)

        prov_info["elapsedSec"] = round(time.perf_counter() - t_fetch, 6)
        tel["provider"] = prov_info

        _cache_set(ckey, hits)
        out = hits[:k]
        _set_hits_telemetry(tel, hits, out)
        tel["elapsedSec"] = round(time.perf_counter() - t_start, 6)
        if telemetry is not None:
            telemetry.update(tel)
        return out
