# DEBUG prints added with prefix [WEB][ORCH]
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
import time

from ..core.settings import SETTINGS
from .duckduckgo import DuckDuckGoProvider
from .provider import SearchHit
from .orchestrator_common import (
    _as_int, _as_float, _as_bool, _as_str,
    condense_doc, content_quality_score,
    _dedupe_by_host, score_hit, _head_tail,
    _fetch_round,
)

def _host_only(u: str) -> str:
    try:
        from urllib.parse import urlparse
        h = (urlparse(u).hostname or "").lower()
        return h or ""
    except Exception:
        return ""

async def build_web_block(query: str, k: Optional[int] = None, per_url_timeout_s: Optional[float] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    tel: Dict[str, Any] = {"query": (query or "").strip()}
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
    per_timeout = (float(per_url_timeout_s) if per_url_timeout_s is not None else _as_float("web_fetch_timeout_sec"))
    start_time = time.perf_counter()

    print(f"[WEB][ORCH] build_web_block query={tel['query']!r} k={cfg_k} overfetch_factor={overfetch_factor} max_parallel={max_parallel} per_doc_budget={per_doc_budget} total_char_budget={total_char_budget}")

    provider = DuckDuckGoProvider()
    overfetch = max(cfg_k + overfetch_min_extra, int(round(cfg_k * overfetch_factor)))
    tel["search"] = {"requestedK": cfg_k, "overfetch": overfetch}
    t0 = time.perf_counter()
    try:
        hits: List[SearchHit] = await provider.search(query, k=overfetch, telemetry=tel["search"])
    except Exception as e:
        print(f"[WEB][ORCH] SEARCH ERROR type={type(e).__name__} msg={e}")
        tel["error"] = {"stage": "search", "type": type(e).__name__, "msg": str(e)}
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        return None, tel
    tel["search"]["elapsedSecTotal"] = round(time.perf_counter() - t0, 6)

    print(f"[WEB][ORCH] search hits={len(hits)} dt={tel['search']['elapsedSecTotal']}s")
    if hits:
        preview = [
            f"{(h.title or '')[:60]!r} @ {_host_only(h.url or '')}"
            for h in hits[:min(6, len(hits))]
        ]
        print(f"[WEB][ORCH] hits preview: {preview}")

    if not hits:
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        return None, tel

    seen_urls = set()
    scored: List[Tuple[int, SearchHit]] = []
    for idx, h in enumerate(hits):
        u = (h.url or "").strip()
        if not u:
            continue
        if u in seen_urls:
            continue
        seen_urls.add(u)
        s = score_hit(h, query)
        scored.append((s, h))
    tel["scoring"] = {"inputHits": len(hits), "scored": len(scored)}
    print(f"[WEB][ORCH] scored={len(scored)} (unique urls), top score={max((s for s,_ in scored), default=-1)}")

    if not scored:
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        return None, tel

    top_hits = _dedupe_by_host(scored, cfg_k)
    tel["scoring"]["picked"] = len(top_hits)
    urls = [h.url for h in top_hits]
    meta = [(h.title or h.url, h.url) for h in top_hits]

    print(f"[WEB][ORCH] picked hosts={[_host_only(u) for u in urls]}")

    t_f = time.perf_counter()
    tel["fetch1"] = {}
    results = await _fetch_round(
        urls, meta, per_url_timeout_s=per_timeout, max_parallel=max_parallel, use_js=False, telemetry=tel["fetch1"]
    )
    dt_f = time.perf_counter() - t_f
    tel["fetch1"]["roundSec"] = round(dt_f, 6)

    texts: List[Tuple[str, str, str]] = []
    quality_scores: List[float] = []
    for original_url, res in results:
        if not res:
            continue
        final_url, status, text = res
        title = next((t for (t, u) in meta if u == original_url), final_url)
        qscore = content_quality_score(text or "")
        quality_scores.append(qscore)
        if text:
            texts.append((title, final_url, text))
    tel["fetch1"]["docs"] = {"ok": len(texts), "qAvg": (sum(quality_scores)/len(quality_scores) if quality_scores else 0.0)}

    print(f"[WEB][ORCH] fetch1 ok={tel['fetch1']['docs']['ok']} qAvg={round(tel['fetch1']['docs']['qAvg'],4) if quality_scores else 0.0} dt={tel['fetch1']['roundSec']}s")

    try_js = False
    if enable_js_retry and quality_scores:
        avg_q = sum(quality_scores) / len(quality_scores)
        lowish = sum(1 for q in quality_scores if q < js_low_q_thresh)
        if avg_q < js_avg_q_thresh or (lowish / max(1, len(quality_scores))) >= js_lowish_ratio:
            try_js = True
        tel["jsRetry"] = {
            "considered": True,
            "triggered": try_js,
            "avgQ": round(avg_q, 4),
            "lowishRatio": round((lowish / max(1, len(quality_scores))), 4),
            "thresholds": {"avg": js_avg_q_thresh, "low": js_low_q_thresh, "ratio": js_lowish_ratio},
        }
    else:
        tel["jsRetry"] = {"considered": bool(enable_js_retry), "triggered": False}

    print(f"[WEB][ORCH] jsRetry considered={tel['jsRetry']['considered']} triggered={tel['jsRetry']['triggered']} details={tel['jsRetry']}")

    if try_js:
        js_timeout   = min(per_timeout + js_timeout_add, js_timeout_cap)
        js_parallel  = max(js_min_parallel, max_parallel + js_parallel_delta)
        tel["fetch2"] = {"timeoutSec": js_timeout, "maxParallel": js_parallel}
        results_js = await _fetch_round(
            urls, meta, per_url_timeout_s=js_timeout, max_parallel=js_parallel, use_js=True, telemetry=tel["fetch2"]
        )
        texts_js: List[Tuple[str, str, str]] = []
        for original_url, res in results_js:
            if not res:
                continue
            final_url, status, text = res
            title = next((t for (t, u) in meta if u == original_url), final_url)
            if text:
                texts_js.append((title, final_url, text))
        if texts_js:
            print(f"[WEB][ORCH] fetch2(js) replaced docs ok={len(texts_js)} (prev {len(texts)})")
            texts = texts_js
        else:
            print("[WEB][ORCH] fetch2(js) produced no better docs; keeping fetch1 results")

    if not texts:
        print("[WEB][ORCH] no texts after fetch; aborting")
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        return None, tel

    # Preview top few docs’ first 120 chars for sanity
    previews = []
    for t, u, body in texts[:min(3, len(texts))]:
        previews.append({"title": (t or "")[:80], "host": _host_only(u), "bodyPreview": (body or "").strip().replace("\n"," ")[:120]})
    print(f"[WEB][ORCH] doc previews (top 3): {previews}")

    texts.sort(key=lambda t: content_quality_score(t[2]), reverse=True)
    chunks: List[str] = []
    for title, final_url, text in texts:
        chunk = condense_doc(title, final_url, text, max_chars=per_doc_budget)
        chunks.append(chunk)

    header = header_tpl.format(query=query)
    sep = _as_str("web_orch_block_separator")
    available = max(_as_int("web_orch_min_block_reserve"), total_char_budget - len(header) - len(sep))
    block_parts: List[str] = []
    used = 0
    for idx, ch in enumerate(chunks):
        cl = len(ch)
        sep_len = (len(sep) if block_parts else 0)
        if used + cl + sep_len > available:
            shrunk = _head_tail(ch, max(min_chunk_after, available - used - sep_len))
            if len(shrunk) > min_chunk_after:
                block_parts.append(shrunk)
                used += len(shrunk) + sep_len
            print(f"[WEB][ORCH] assembly hit budget; idx={idx} used={used} available={available} added_shrunk={len(block_parts[-1]) if block_parts else 0}")
            break
        block_parts.append(ch)
        used += cl + sep_len

    print(f"[WEB][ORCH] assembly chunksPicked={len(block_parts)} available={available} headerChars={len(header)}")

    body = sep.join(block_parts)
    block = f"{header}{sep}{body}" if body else header

    tel["assembly"] = {
        "chunksPicked": len(block_parts),
        "chars": len(block),
        "available": available,
        "headerChars": len(header),
    }
    tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)

    print(f"[WEB][ORCH] DONE chars={tel['assembly']['chars']} elapsed={tel['elapsedSec']}s")
    return block, tel
