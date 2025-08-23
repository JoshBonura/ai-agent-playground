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

from .provider import SearchHit

# -------- simple in-memory cache (store superset = 10) -----------------------
_CACHE: dict[str, Tuple[float, List[SearchHit]]] = {}
CACHE_TTL_SEC = 300  # 5 minutes
CACHE_SUPERSET_K = 10

def _cache_key(query: str) -> str:
    return (query or "").strip().lower()

def _cache_get(query: str) -> Optional[List[SearchHit]]:
    key = _cache_key(query)
    v = _CACHE.get(key)
    if not v:
        return None
    ts, hits = v
    if (time.time() - ts) > CACHE_TTL_SEC:
        _CACHE.pop(key, None)
        return None
    return hits

def _cache_set(query: str, hits: List[SearchHit]) -> None:
    _CACHE[_cache_key(query)] = (time.time(), hits)

def _host(u: str) -> str:
    try:
        h = (urlparse(u).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""

# -------- DDGS (official client) ---------------------------------------------
def _ddg_sync_search(query: str, k: int) -> List[SearchHit]:
    results: List[SearchHit] = []
    if DDGS is None:
        print(f"[{time.strftime('%X')}] ddg: PROVIDER MISSING (DDGS=None)")
        return results
    with DDGS() as ddg:
        for i, r in enumerate(ddg.text(query, max_results=max(1, k),
                                       safesearch="moderate", region="us-en")):
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
        """
        Returns top-k SearchHit results via DDGS.

        Added prints:
          - START with normalized query, k
          - CACHE HIT / MISS with timing
          - For fetched results: total count, top items (idx, host, title, url)
          - RETURN with timing and top titles
        """
        t0 = time.time()
        q_norm = (query or "").strip()
        if not q_norm:
            print("ddg: empty query")
            return []

        print(f"[{time.strftime('%X')}] ddg: START q={q_norm!r} k={k}")

        # superset cache
        cached = _cache_get(q_norm)
        if cached is not None:
            dt = time.time() - t0
            out = cached[:k]
            top_preview = [f"{h.rank}:{_host(h.url)}:{(h.title or '')[:60]}" for h in out[:5]]
            print(f"[{time.strftime('%X')}] ddg: CACHE HIT dt={dt:.2f}s hits={len(out)} top={top_preview}")
            return out

        # fetch superset once
        sup_k = max(k, CACHE_SUPERSET_K)
        hits: List[SearchHit] = []
        if DDGS is not None:
            try:
                step = time.time()
                hits = await asyncio.to_thread(_ddg_sync_search, q_norm, sup_k)
                dt_fetch = time.time() - step
                print(f"[{time.strftime('%X')}] ddg: HITS RECEIVED dt={dt_fetch:.2f}s count={len(hits)}")
                # verbose preview of first few results
                for h in hits[:5]:
                    print(f"[{time.strftime('%X')}] ddg:   {h.rank:>2} | host={_host(h.url)} | title={(h.title or '')[:80]!r} | url={h.url}")
            except Exception as e:
                print(f"[{time.strftime('%X')}] ddg: ERROR {e}")
        else:
            print(f"[{time.strftime('%X')}] ddg: SKIP (DDGS unavailable)")

        # store superset and return slice
        _cache_set(q_norm, hits)
        dt = time.time() - t0
        out = hits[:k]
        top_titles = [h.title for h in out[:3]]
        print(f"[{time.strftime('%X')}] ddg: RETURN dt={dt:.2f}s hits={len(out)} top={top_titles}")
        return out
