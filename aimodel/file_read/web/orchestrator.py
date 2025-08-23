# aimodel/file_read/web/orchestrator.py
from __future__ import annotations
from typing import List, Tuple
from urllib.parse import urlparse
import time
import re

from .duckduckgo import DuckDuckGoProvider
from .provider import SearchHit
from .fetch import fetch_many

DEFAULT_K = 2                 # fewer sources by default
MAX_BLOCK_TOKENS_EST = 700    # respect ~char budget below
TOTAL_CHAR_BUDGET = 1600      # ~ 400 tokens (≈4 chars/token)
PER_DOC_CHAR_BUDGET = 900     # trim each page harder
MAX_PARALLEL_FETCH = 2        # avoid overfetching & reduce prompt bloat

def _clean_ws(s: str) -> str:
    return " ".join((s or "").split())

def _head_tail(text: str, max_chars: int) -> str:
    if not text or len(text) <= max_chars:
        return _clean_ws(text)
    head = max_chars - max(200, max_chars // 3)
    tail = max_chars - head
    return _clean_ws(text[:head] + " … " + text[-tail:])

def condense_doc(title: str, url: str, text: str, max_chars: int = PER_DOC_CHAR_BUDGET) -> str:
    # keep title, final URL, and a trimmed body
    body = _head_tail(text or "", max_chars)
    safe_title = _clean_ws(title or url)
    return f"- {safe_title}\n  {url}\n  {body}"

def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h

def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"\w+", (s or "").lower()) if t]

def score_hit(hit: SearchHit, query: str) -> int:
    """
    Generic, content-based scoring (no hardcoded domains, no date/month/year rules).
    Signals:
      - exact phrase in title (+3) / substring in title (+2)
      - token coverage in title (+0..2)
      - token touch in snippet (+1 if any)
    """
    score = 0
    q = (query or "").strip().lower()
    title = (hit.title or "").strip()
    snippet = (hit.snippet or "").strip()
    title_l = title.lower()
    snip_l  = snippet.lower()

    if q:
        if title_l == q:
            score += 3
        elif q in title_l:
            score += 2

    qtoks = _tokens(q)
    if qtoks:
        cov_title = sum(1 for t in qtoks if t in title_l)
        if cov_title == len(qtoks):
            score += 2
        elif cov_title > 0:
            score += 1

        cov_snip = sum(1 for t in qtoks if t in snip_l)
        if cov_snip > 0:
            score += 1

    return score

async def build_web_block(query: str, k: int = DEFAULT_K, per_url_timeout_s: float = 8.0) -> str | None:
    start_time = time.time()
    print(f"[orchestrator] IN  @ {start_time:.3f}s | query={query!r}")

    t0 = time.perf_counter()
    provider = DuckDuckGoProvider()

    # --- SEARCH (light overfetch) ---
    overfetch = max(k + 1, int(k * 1.5))
    print(f"[orchestrator] SEARCH start overfetch={overfetch} k={k}")
    try:
        hits: List[SearchHit] = await provider.search(query, k=overfetch)
    except Exception as e:
        print(f"[orchestrator] ERROR during search for {query!r}: {e}")
        return None
    print(f"[orchestrator] SEARCH done hits={len(hits)} dt={time.perf_counter() - t0:.3f}s")

    if not hits:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no hits | elapsed={time.time()-start_time:.3f}s")
        return None

    # --- SCORING / DEDUPE ---
    print(f"[orchestrator] SCORING generic (no hardcoded boosts)")
    seen = set()
    scored: List[Tuple[int, SearchHit]] = []
    for idx, h in enumerate(hits):
        u = (h.url or "").strip()
        if not u:
            print(f"[orchestrator]   skip[{idx}] empty url")
            continue
        if u in seen:
            print(f"[orchestrator]   dup [{idx}] host={_host(u)} title={(h.title or '')[:60]!r}")
            continue
        seen.add(u)
        s = score_hit(h, query)
        scored.append((s, h))
        print(f"[orchestrator]   meta[{idx}] score={s} host={_host(u)} title={(h.title or '')[:80]!r} url={u}")

    if not scored:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no unique hits | elapsed={time.time()-start_time:.3f}s")
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    top_hits = [h for _, h in scored[:k]]

    for i, h in enumerate(top_hits, 1):
        print(f"[orchestrator] PICK {i}/{k} score={score_hit(h, query)} host={_host(h.url)} title={(h.title or '')[:80]!r}")

    # --- FETCH (tighter caps) ---
    urls = [h.url for h in top_hits]
    meta = [(h.title or h.url, h.url) for h in top_hits]
    print(f"[orchestrator] FETCH start urls={[ _host(u) for u in urls ]}")

    t_f = time.perf_counter()
    results = await fetch_many(
        urls,
        per_timeout_s=per_url_timeout_s,
        cap_chars=min(2000, PER_DOC_CHAR_BUDGET * 2),
        max_parallel=MAX_PARALLEL_FETCH,
    )
    dt_f = time.perf_counter() - t_f
    print(f"[orchestrator] FETCH done n={len(results)} dt={dt_f:.3f}s")

    chunks: List[str] = []
    for original_url, res in results:
        if not res:
            print(f"[orchestrator]   fetch MISS url={original_url}")
            continue
        final_url, status, text = res
        title = next((t for (t, u) in meta if u == original_url), final_url)
        tl = len(text or "")
        print(f"[orchestrator]   fetch OK   status={status} host={_host(final_url)} text_len={tl} title={(title or '')[:80]!r}")
        if not text:
            continue
        chunk = condense_doc(title, final_url, text, max_chars=PER_DOC_CHAR_BUDGET)
        chunks.append(chunk)
        print(f"[orchestrator]   chunk len={len(chunk)} host={_host(final_url)}")

    if not chunks:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no chunks | elapsed={time.time()-start_time:.3f}s")
        return None

    # --- ENFORCE TOTAL BUDGET ---
    header = f"Web findings for: {query}"
    available = max(200, TOTAL_CHAR_BUDGET - len(header) - 2)
    block_parts: List[str] = []
    used = 0
    for idx, ch in enumerate(chunks):
        cl = len(ch)
        sep = (2 if block_parts else 0)
        if used + cl + sep > available:
            shrunk = _head_tail(ch, max(200, available - used - sep))
            print(f"[orchestrator]   budget hit at chunk[{idx}] orig={cl} shrunk={len(shrunk)} used_before={used} avail={available}")
            if len(shrunk) > 200:
                block_parts.append(shrunk)
                used += len(shrunk) + sep
            break
        block_parts.append(ch)
        used += cl + sep
        print(f"[orchestrator]   take chunk[{idx}] len={cl} used_total={used}/{available}")

    body = "\n\n".join(block_parts)
    block = f"{header}\n\n{body}"

    end_time = time.time()
    print(f"[orchestrator] OUT @ {end_time:.3f}s | elapsed={end_time-start_time:.3f}s | chunks={len(block_parts)} | chars={len(block)}")
    return block
