# aimodel/file_read/web/duckduckgo.py
from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Any
import asyncio, time
from urllib.parse import urlparse

try:
    from ddgs import DDGS  # type: ignore
except Exception:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        DDGS = None  # type: ignore

from ..core.settings import SETTINGS
from .provider import SearchHit

_CACHE: dict[str, Tuple[float, List[SearchHit]]] = {}

def _cache_key(query: str) -> str:
    return (query or "").strip().lower()

def _host(u: str) -> str:
    try:
        h = (urlparse(u).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""

def _cache_get(query: str) -> Optional[List[SearchHit]]:
    eff = SETTINGS.effective()
    ttl = int(eff["web_search_cache_ttl_sec"])
    key = _cache_key(query)
    v = _CACHE.get(key)
    if not v:
        return None
    ts, hits = v
    if (time.time() - ts) > ttl:
        _CACHE.pop(key, None)
        return None
    return hits

def _cache_set(query: str, hits: List[SearchHit]) -> None:
    _CACHE[_cache_key(query)] = (time.time(), hits)

def _ddg_sync_search(query: str, k: int, *, region: str, safesearch: str) -> List[SearchHit]:
    results: List[SearchHit] = []
    if DDGS is None:
        return results
    with DDGS() as ddg:
        for i, r in enumerate(ddg.text(query, max_results=max(1, k), safesearch=safesearch, region=region)):
            title = (r.get("title") or "").strip()
            url = (r.get("href") or "").strip()
            snippet: Optional[str] = (r.get("body") or "").strip() or None
            if not url:
                continue
            results.append(SearchHit(title=title or url, url=url, snippet=snippet, rank=i))
            if i + 1 >= k:
                break
    return results

class DuckDuckGoProvider:
    async def search(self, query: str, k: int = 3, telemetry: Optional[Dict[str, Any]] = None) -> List[SearchHit]:
        t_start = time.perf_counter()
        eff = SETTINGS.effective()
        q_norm = (query or "").strip()
        if not q_norm:
            if telemetry is not None:
                telemetry.update({"query": q_norm, "k": int(k), "supersetK": int(k), "elapsedSec": round(time.perf_counter() - t_start, 6), "cache": {"hit": False}})
            return []
        superset_k = max(int(k), int(eff["web_search_cache_superset_k"]))
        region = str(eff["web_search_region"])
        safesearch = str(eff["web_search_safesearch"])

        tel: Dict[str, Any] = {"query": q_norm, "k": int(k), "supersetK": superset_k, "region": region, "safesearch": safesearch}
        t_cache = time.perf_counter()
        cached = _cache_get(q_norm)
        tel["cache"] = {"hit": cached is not None, "elapsedSec": round(time.perf_counter() - t_cache, 6)}
        if cached is not None:
            out = cached[:k]
            tel["hits"] = {
                "total": len(cached),
                "returned": len(out),
                "top": [f"{h.rank}:{_host(h.url)}:{(h.title or '')[:60]}" for h in out[:5]],
            }
            tel["elapsedSec"] = round(time.perf_counter() - t_start, 6)
            if telemetry is not None:
                telemetry.update(tel)
            return out

        hits: List[SearchHit] = []
        prov_info: Dict[str, Any] = {"available": DDGS is not None}
        t_fetch = time.perf_counter()
        if DDGS is not None:
            try:
                hits = await asyncio.to_thread(_ddg_sync_search, q_norm, superset_k, region=region, safesearch=safesearch)
                prov_info["errorType"] = None
                prov_info["errorMsg"] = None
            except Exception as e:
                prov_info["errorType"] = type(e).__name__
                prov_info["errorMsg"] = str(e)
                hits = []
        else:
            prov_info["errorType"] = "ProviderUnavailable"
            prov_info["errorMsg"] = "DDGS is not installed or failed to import."
        prov_info["elapsedSec"] = round(time.perf_counter() - t_fetch, 6)
        tel["provider"] = prov_info

        _cache_set(q_norm, hits)
        out = hits[:k]
        tel["hits"] = {
            "total": len(hits),
            "returned": len(out),
            "top": [f"{h.rank}:{_host(h.url)}:{(h.title or '')[:60]}" for h in out[:5]],
        }
        tel["elapsedSec"] = round(time.perf_counter() - t_start, 6)
        if telemetry is not None:
            telemetry.update(tel)
        return out
