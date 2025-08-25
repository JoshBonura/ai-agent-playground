# aimodel/file_read/web/duckduckgo.py
from __future__ import annotations
from typing import List, Optional, Tuple
import asyncio, time
from urllib.parse import urlparse

# Prefer new package; fallback for compatibility
try:
    from ddgs import DDGS  # type: ignore
except Exception:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        DDGS = None  # no provider

from ..core.settings import SETTINGS
from .provider import SearchHit

# -------- simple in-memory cache (superset caching) --------------------------
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
    eff = SETTINGS.effective()  # no fallbacks allowed
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

# -------- DDGS (official client) --------------------------------------------
def _ddg_sync_search(query: str, k: int, *, region: str, safesearch: str) -> List[SearchHit]:
    results: List[SearchHit] = []
    if DDGS is None:
        print(f"[{time.strftime('%X')}] ddg: PROVIDER MISSING (DDGS=None)")
        return results
    with DDGS() as ddg:
        for i, r in enumerate(ddg.text(query, max_results=max(1, k),
                                       safesearch=safesearch, region=region)):
            title = (r.get("title") or "").strip()
            url = (r.get("href") or "").strip()
            snippet: Optional[str] = (r.get("body") or "").strip() or None
            if not url:
                continue
            results.append(SearchHit(title=title or url, url=url, snippet=snippet, rank=i))
            if i + 1 >= k:
                break
    return results

# -------- public provider ----------------------------------------------------
class DuckDuckGoProvider:
    async def search(self, query: str, k: int = 3) -> List[SearchHit]:
        eff = SETTINGS.effective()  # strict read; raise if missing
        q_norm = (query or "").strip()
        if not q_norm:
            return []

        superset_k = max(int(k), int(eff["web_search_cache_superset_k"]))
        region = str(eff["web_search_region"])
        safesearch = str(eff["web_search_safesearch"])
        verbose = bool(eff["web_search_debug_logging"])

        t0 = time.time()
        if verbose:
            print(f"[{time.strftime('%X')}] ddg: START q={q_norm!r} k={k}")

        # cache
        cached = _cache_get(q_norm)
        if cached is not None:
            out = cached[:k]
            if verbose:
                top_preview = [f"{h.rank}:{_host(h.url)}:{(h.title or '')[:60]}" for h in out[:5]]
                print(f"[{time.strftime('%X')}] ddg: CACHE HIT dt={time.time()-t0:.2f}s hits={len(out)} top={top_preview}")
            return out

        # fetch superset once
        hits: List[SearchHit] = []
        if DDGS is not None:
            try:
                step = time.time()
                hits = await asyncio.to_thread(_ddg_sync_search, q_norm, superset_k,
                                               region=region, safesearch=safesearch)
                if verbose:
                    print(f"[{time.strftime('%X')}] ddg: HITS RECEIVED dt={time.time()-step:.2f}s count={len(hits)}")
                    for h in hits[:5]:
                        print(f"[{time.strftime('%X')}] ddg:   {h.rank:>2} | host={_host(h.url)} | "
                              f"title={(h.title or '')[:80]!r}")
            except Exception as e:
                print(f"[{time.strftime('%X')}] ddg: ERROR {e}")
        else:
            print(f"[{time.strftime('%X')}] ddg: SKIP (DDGS unavailable)")

        _cache_set(q_norm, hits)
        out = hits[:k]
        if verbose:
            print(f"[{time.strftime('%X')}] ddg: RETURN dt={time.time()-t0:.2f}s hits={len(out)}")
        return out
