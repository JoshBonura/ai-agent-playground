# aimodel/file_read/web/orchestrator.py
from __future__ import annotations
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import time
import re

from ..core.settings import SETTINGS
from .duckduckgo import DuckDuckGoProvider
from .provider import SearchHit
from .fetch import fetch_many  # optional JS path resolved dynamically (see below)

# ===== helpers to read config (strict: no silent defaults) ====================

def _req(key: str):
    return SETTINGS[key]

def _as_int(key: str) -> int: return int(_req(key))
def _as_float(key: str) -> float: return float(_req(key))
def _as_bool(key: str) -> bool: return bool(_req(key))
def _as_str(key: str) -> str:
    v = _req(key)
    return "" if v is None else str(v)

# ===== small utils ============================================================

def _clean_ws(s: str) -> str:
    return " ".join((s or "").split())

def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    pref = _as_str("web_orch_www_prefix")
    return h[len(pref):] if pref and h.startswith(pref) else h

def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"\w+", (s or "").lower()) if t]

def _head_tail(text: str, max_chars: int) -> str:
    """
    Trim long text to head/tail, using settings:
      - web_orch_head_fraction
      - web_orch_tail_min_chars
      - web_orch_ellipsis
    Mirrors the old behavior but configurable.
    """
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return _clean_ws(text)

    head_frac      = _as_float("web_orch_head_fraction")      # e.g., 0.67
    tail_min_chars = _as_int("web_orch_tail_min_chars")       # e.g., 200
    ellipsis       = _as_str("web_orch_ellipsis")             # e.g., " … "

    head = int(max_chars * head_frac)
    tail = max_chars - head
    if tail < tail_min_chars:
        head = max(1, max_chars - tail_min_chars)
        tail = tail_min_chars

    return _clean_ws(text[:head] + ellipsis + text[-tail:])

def condense_doc(title: str, url: str, text: str, *, max_chars: int) -> str:
    body = _head_tail(text or "", max_chars)
    safe_title = _clean_ws(title or url)
    bullet = _as_str("web_orch_bullet_prefix") or "- "
    indent = _as_str("web_orch_indent_prefix") or "  "
    return f"{bullet}{safe_title}\n{indent}{url}\n{indent}{body}"

# ===== scoring (generic; no domain/date heuristics) ===========================

def score_hit(hit: SearchHit, query: str) -> int:
    """
    Generic, content-based scoring.
      - exact phrase in title (+web_orch_score_w_exact)
      - substring in title (+web_orch_score_w_substr)
      - token coverage in title (+0..web_orch_score_w_title_full/title_part)
      - any token in snippet (+web_orch_score_w_snip_touch)
    """
    w_exact      = _as_int("web_orch_score_w_exact")
    w_substr     = _as_int("web_orch_score_w_substr")
    w_title_full = _as_int("web_orch_score_w_title_full")
    w_title_part = _as_int("web_orch_score_w_title_part")
    w_snip_touch = _as_int("web_orch_score_w_snip_touch")

    score = 0
    q = (query or "").strip().lower()
    title = (hit.title or "").strip()
    snippet = (hit.snippet or "").strip()
    title_l = title.lower()
    snip_l  = snippet.lower()

    if q:
        if title_l == q:
            score += w_exact
        elif q in title_l:
            score += w_substr

    qtoks = _tokens(q)
    if qtoks:
        cov_title = sum(1 for t in qtoks if t in title_l)
        if cov_title == len(qtoks) and len(qtoks) > 0:
            score += w_title_full
        elif cov_title > 0:
            score += w_title_part
        cov_snip = sum(1 for t in qtoks if t in snip_l)
        if cov_snip > 0:
            score += w_snip_touch

    return score

# ===== quality estimate (generic; configurable penalties) =====================

def _type_ratio(text: str, sub: str) -> float:
    if not text:
        return 1.0
    cnt = text.lower().count(sub)
    return float(cnt) / max(1, len(text))

def content_quality_score(text: str) -> float:
    if not text:
        return 0.0
    t = text.strip()
    n = len(t)

    len_div     = _as_float("web_orch_q_len_norm_divisor")
    w_len       = _as_float("web_orch_q_len_weight")
    w_div       = _as_float("web_orch_q_diversity_weight")

    length_score = min(1.0, n / len_div) if len_div > 0 else 0.0

    toks = _tokens(t)
    if not toks:
        return 0.1 * length_score  # tiny signal if no tokens

    uniq = len(set(toks))
    diversity = uniq / max(1.0, float(len(toks)))

    pen = 0.0
    # penalties: [{"token": str, "mult": float, "cap": float}, ...]
    for rule in _req("web_orch_q_penalties"):
        token = str(rule.get("token") or "")
        mult  = float(rule.get("mult") or 0.0)
        cap   = float(rule.get("cap") or 1.0)
        pen += min(cap, _type_ratio(t, token) * mult)

    raw = (w_len * length_score) + (w_div * diversity) - pen
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

# ===== fetch layer ============================================================

async def _fetch_round(
    urls: List[str],
    meta: List[Tuple[str, str]],
    per_url_timeout_s: float,
    max_parallel: int,
    use_js: bool = False,
) -> List[Tuple[str, Optional[Tuple[str, int, str]]]]:

    fetch_fn = fetch_many
    if use_js:
        try:
            from . import fetch as _fetch_mod  # type: ignore
            fetch_fn = getattr(_fetch_mod, "fetch_many_js", fetch_many)
        except Exception:
            fetch_fn = fetch_many

    # Cap per doc by multiplier, but never exceed global max bytes/chars
    cap_mult        = _as_float("web_orch_fetch_cap_multiplier")
    per_doc_budget  = _as_int("web_orch_per_doc_char_budget")
    fetch_max_chars = _as_int("web_fetch_max_chars")
    per_doc_cap     = min(int(per_doc_budget * cap_mult), fetch_max_chars)

    results = await fetch_fn(
        urls,
        per_timeout_s=per_url_timeout_s,
        cap_chars=per_doc_cap,
        max_parallel=max_parallel,
    )
    return results

# ===== main ===================================================================

async def build_web_block(query: str, k: Optional[int] = None, per_url_timeout_s: Optional[float] = None) -> str | None:
    # pull config each call (to honor hot-reloads)
    cfg_k               = (int(k) if k is not None else _as_int("web_orch_default_k"))
    total_char_budget   = _as_int("web_orch_total_char_budget")
    per_doc_budget      = _as_int("web_orch_per_doc_char_budget")
    max_parallel        = _as_int("web_orch_max_parallel_fetch")
    overfetch_factor    = _as_float("web_orch_overfetch_factor")
    overfetch_min_extra = _as_int("web_orch_overfetch_min_extra")

    enable_js_retry     = _as_bool("web_orch_enable_js_retry")
    js_avg_q_thresh     = _as_float("web_orch_js_retry_avg_q")
    js_low_q_thresh     = _as_float("web_orch_js_retry_low_q")
    js_lowish_ratio     = _as_float("web_orch_js_retry_lowish_ratio")
    js_timeout_add      = _as_float("web_orch_js_retry_timeout_add")
    js_timeout_cap      = _as_float("web_orch_js_retry_timeout_cap")
    js_parallel_delta   = _as_int("web_orch_js_retry_parallel_delta")
    js_min_parallel     = _as_int("web_orch_js_retry_min_parallel")

    header_tpl          = _as_str("web_block_header")
    sep_str             = _as_str("web_orch_block_separator")
    min_block_reserve   = _as_int("web_orch_min_block_reserve")
    min_chunk_after     = _as_int("web_orch_min_chunk_after_shrink")

    # timeouts
    per_timeout = (float(per_url_timeout_s)
                   if per_url_timeout_s is not None
                   else _as_float("web_fetch_timeout_sec"))

    start_time = time.time()
    print(f"[orchestrator] IN  @ {start_time:.3f}s | query={query!r}")

    provider = DuckDuckGoProvider()

    # --- SEARCH (configurable overfetch) ---
    overfetch = max(cfg_k + overfetch_min_extra, int(round(cfg_k * overfetch_factor)))
    print(f"[orchestrator] SEARCH start overfetch={overfetch} k={cfg_k}")

    t0 = time.perf_counter()
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

    top_hits = _dedupe_by_host(scored, cfg_k)
    for i, h in enumerate(top_hits, 1):
        # reuse computed scores when printing
        s = next((sc for sc, hh in scored if hh is h), 0)
        print(f"[orchestrator] PICK {i}/{cfg_k} score={s} host={_host(h.url)} title={(h.title or '')[:80]!r}")

    # --- FETCH ROUND 1 (static) ---
    urls = [h.url for h in top_hits]
    meta = [(h.title or h.url, h.url) for h in top_hits]
    print(f"[orchestrator] FETCH[1] start urls={[ _host(u) for u in urls ]}")

    t_f = time.perf_counter()
    results = await _fetch_round(
        urls, meta, per_url_timeout_s=per_timeout, max_parallel=max_parallel, use_js=False
    )
    dt_f = time.perf_counter() - t_f
    print(f"[orchestrator] FETCH[1] done n={len(results)} dt={dt_f:.3f}s")

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

    # --- JS retry decision (configurable thresholds) ---
    try_js = False
    if enable_js_retry and quality_scores:
        avg_q = sum(quality_scores) / len(quality_scores)
        lowish = sum(1 for q in quality_scores if q < js_low_q_thresh)
        if avg_q < js_avg_q_thresh or (lowish / max(1, len(quality_scores))) >= js_lowish_ratio:
            try_js = True

    if try_js:
        print("[orchestrator] FETCH[2-JS] trying JS-rendered fetch due to low content quality")
        js_timeout   = min(per_timeout + js_timeout_add, js_timeout_cap)
        js_parallel  = max(js_min_parallel, max_parallel + js_parallel_delta)

        results_js = await _fetch_round(
            urls, meta, per_url_timeout_s=js_timeout, max_parallel=js_parallel, use_js=True
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

        if texts_js:
            texts = texts_js

    if not texts:
        print(f"[orchestrator] OUT @ {time.time():.3f}s | no chunks | elapsed={time.time()-start_time:.3f}s")
        return None

    # --- Build chunks; order by quality ---
    texts.sort(key=lambda t: content_quality_score(t[2]), reverse=True)

    chunks: List[str] = []
    for title, final_url, text in texts:
        chunk = condense_doc(title, final_url, text, max_chars=per_doc_budget)
        chunks.append(chunk)
        print(f"[orchestrator]   chunk len={len(chunk)} host={_host(final_url)}")

    # --- Enforce total budget ---
    header = header_tpl.format(query=query)
    sep = _as_str("web_orch_block_separator")
    available = max(_as_int("web_orch_min_block_reserve"),
                    total_char_budget - len(header) - len(sep))
    block_parts: List[str] = []
    used = 0
    for idx, ch in enumerate(chunks):
        cl = len(ch)
        sep_len = (len(sep) if block_parts else 0)
        if used + cl + sep_len > available:
            shrunk = _head_tail(ch, max(min_chunk_after, available - used - sep_len))
            print(f"[orchestrator]   budget hit at chunk[{idx}] orig={cl} shrunk={len(shrunk)} used_before={used} avail={available}")
            if len(shrunk) > min_chunk_after:
                block_parts.append(shrunk)
                used += len(shrunk) + sep_len
            break
        block_parts.append(ch)
        used += cl + sep_len
        print(f"[orchestrator]   take chunk[{idx}] len={cl} used_total={used}/{available}")

    body = sep.join(block_parts)
    block = f"{header}{sep}{body}" if body else header

    end_time = time.time()
    print(f"[orchestrator] OUT @ {end_time:.3f}s | elapsed={end_time-start_time:.3f}s | chunks={len(block_parts)} | chars={len(block)}")
    return block
