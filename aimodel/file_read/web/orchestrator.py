# aimodel/file_read/web/orchestrator.py
from __future__ import annotations
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import time
import re

from .duckduckgo import DuckDuckGoProvider
from .provider import SearchHit
from .fetch import fetch_many  # optional JS path resolved dynamically (see below)

DEFAULT_K = 3                 # fewer sources by default
MAX_BLOCK_TOKENS_EST = 700    # respect ~char budget below
TOTAL_CHAR_BUDGET = 2000      # ~ 400 tokens (≈4 chars/token)
PER_DOC_CHAR_BUDGET = 1200    # trim each page harder
MAX_PARALLEL_FETCH = 4        # small bump for resilience

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

# -------------------- NEW: generic content-quality scoring --------------------

def _type_ratio(text: str, sub: str) -> float:
    # rough indicator: how often a pattern appears (e.g., 'script', '{', etc.)
    if not text:
        return 1.0
    cnt = text.lower().count(sub)
    return float(cnt) / max(1, len(text))

def content_quality_score(text: str) -> float:
    """
    Purely generic quality estimate:
      - + length (more text = better up to a point)
      - + token diversity (unique tokens vs total)
      - - script-ish / code-ish indicators (lots of braces, 'script', 'function')
    No domain/intent/keyword heuristics.
    Returns 0..1 (higher is better).
    """
    if not text:
        return 0.0
    t = text.strip()
    n = len(t)
    # length contribution (sigmoid-like clamp)
    length_score = min(1.0, n / 2000.0)  # ~2k chars reaches 1.0

    toks = _tokens(t)
    if not toks:
        return 0.1 * length_score
    uniq = len(set(toks))
    diversity = uniq / max(1.0, len(toks))
    # penalize obvious boilerplate/code dominance
    penalty = 0.0
    penalty += min(0.3, _type_ratio(t, "<script>") * 50.0)
    penalty += min(0.3, _type_ratio(t, "function(") * 20.0)
    penalty += min(0.2, _type_ratio(t, "{") * 5.0 + _type_ratio(t, "}") * 5.0)

    raw = 0.55 * length_score + 0.55 * diversity - penalty
    return max(0.0, min(1.0, raw))

def _dedupe_by_host(scored_hits: List[Tuple[int, SearchHit]], k: int) -> List[SearchHit]:
    picked: List[SearchHit] = []
    seen_hosts = set()
    for s, h in sorted(scored_hits, key=lambda x: x[0], reverse=True):
        u = (h.url or "").strip()
        if not u:
            continue
        host = _host(u)
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        picked.append(h)
        if len(picked) >= k:
            break
    return picked

# ------------------------------------------------------------------------------

async def _fetch_round(
    urls: List[str],
    meta: List[Tuple[str, str]],
    per_url_timeout_s: float,
    max_parallel: int,
    use_js: bool = False,
) -> List[Tuple[str, Optional[Tuple[str, int, str]]]]:
    """
    One fetch round, optionally using a JS renderer if available.
    If use_js is True, try calling fetch_many_js (if present). Otherwise fall back to fetch_many.
    """
    # Resolve JS-capable fetcher if exported by .fetch (keeps this generic)
    fetch_fn = fetch_many
    if use_js:
        try:
            from . import fetch as _fetch_mod  # type: ignore
            fetch_fn = getattr(_fetch_mod, "fetch_many_js", fetch_many)
        except Exception:
            fetch_fn = fetch_many

    results = await fetch_fn(
        urls,
        per_timeout_s=per_url_timeout_s,
        cap_chars=min(2000, PER_DOC_CHAR_BUDGET * 2),
        max_parallel=max_parallel,
    )
    return results

async def build_web_block(query: str, k: int = DEFAULT_K, per_url_timeout_s: float = 8.0) -> str | None:
    start_time = time.time()
    print(f"[orchestrator] IN  @ {start_time:.3f}s | query={query!r}")

    t0 = time.perf_counter()
    provider = DuckDuckGoProvider()

    # --- SEARCH (wider overfetch, still generic) ---
    overfetch = max(k + 2, int(k * 2))  # slightly wider to beat JS-only pages
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

    # --- SCORING / DEDUPE (no hardcoded boosts) ---
    print(f"[orchestrator] SCORING generic (no hardcoded boosts)")
    seen_urls = set()
    scored: List[Tuple[int, SearchHit]] = []
    for idx, h in enumerate(hits):
        u = (h.url or "").strip()
        if not u:
            print(f"[orchestrator]   skip[{idx}] empty url")
            continue
        if u in seen_urls:
            print(f"[orchestrator]   dup [{idx}] host={_host(u)} title={(h.title or '')[:60]!r}")
            continue
        seen_urls.add(u)
        s = score_hit(h, query)
        scored.append((s, h))
        print(f"[orchestrator]   meta[{idx}] score={s} host={_host(u)} title={(h.title or '')[:80]!r} url={u}")

    if not scored:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no unique hits | elapsed={time.time()-start_time:.3f}s")
        return None

    # Prefer unique hosts among the top scorers
    top_hits = _dedupe_by_host(scored, k)

    for i, h in enumerate(top_hits, 1):
        print(f"[orchestrator] PICK {i}/{k} score={score_hit(h, query)} host={_host(h.url)} title={(h.title or '')[:80]!r}")

    # --- FETCH ROUND 1 (static) ---
    urls = [h.url for h in top_hits]
    meta = [(h.title or h.url, h.url) for h in top_hits]
    print(f"[orchestrator] FETCH[1] start urls={[ _host(u) for u in urls ]}")

    t_f = time.perf_counter()
    results = await _fetch_round(
        urls, meta, per_url_timeout_s=per_url_timeout_s, max_parallel=MAX_PARALLEL_FETCH, use_js=False
    )
    dt_f = time.perf_counter() - t_f
    print(f"[orchestrator] FETCH[1] done n={len(results)} dt={dt_f:.3f}s")

    # Evaluate quality; if overall weak, optionally do a JS-render pass
    texts: List[Tuple[str, str, str]] = []  # (title, final_url, text)
    quality_scores: List[float] = []

    for original_url, res in results:
        if not res:
            print(f"[orchestrator]   fetch MISS url={original_url}")
            continue
        final_url, status, text = res
        title = next((t for (t, u) in meta if u == original_url), final_url)
        tl = len(text or "")
        qscore = content_quality_score(text or "")
        quality_scores.append(qscore)
        print(f"[orchestrator]   fetch OK   status={status} host={_host(final_url)} len={tl} q={qscore:.2f} title={(title or '')[:80]!r}")
        if text:
            texts.append((title, final_url, text))

    # Decide on JS-render retry generically: if most pages are very low-signal
    try_js = False
    if quality_scores:
        avg_q = sum(quality_scores) / len(quality_scores)
        lowish = sum(1 for q in quality_scores if q < 0.45)  # <- raise threshold
        if avg_q < 0.55 or lowish >= max(1, len(quality_scores) // 2):
            try_js = True

    if try_js:
        print("[orchestrator] FETCH[2-JS] trying JS-rendered fetch due to low content quality")
        results_js = await _fetch_round(
            urls, meta, per_url_timeout_s=min(per_url_timeout_s + 4.0, 12.0),
            max_parallel=max(2, MAX_PARALLEL_FETCH - 1), use_js=True
        )
        texts_js: List[Tuple[str, str, str]] = []
        for original_url, res in results_js:
            if not res:
                continue
            final_url, status, text = res
            title = next((t for (t, u) in meta if u == original_url), final_url)
            tl = len(text or "")
            qscore = content_quality_score(text or "")
            print(f"[orchestrator]   fetch JS OK status={status} host={_host(final_url)} len={tl} q={qscore:.2f} title={(title or '')[:80]!r}")
            if text:
                texts_js.append((title, final_url, text))

        # Prefer JS results where they improved the quality score
        if texts_js:
            texts = texts_js

    if not texts:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no chunks | elapsed={time.time()-start_time:.3f}s")
        return None

    # Build chunks; order by generic quality (best first)
    texts.sort(key=lambda t: content_quality_score(t[2]), reverse=True)

    chunks: List[str] = []
    for title, final_url, text in texts:
        chunk = condense_doc(title, final_url, text, max_chars=PER_DOC_CHAR_BUDGET)
        chunks.append(chunk)
        print(f"[orchestrator]   chunk len={len(chunk)} host={_host(final_url)}")

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
