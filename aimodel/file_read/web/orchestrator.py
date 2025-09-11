from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
import time
from collections import defaultdict
from typing import Any

from ..core.request_ctx import get_x_id
from .brave import BraveProvider
from .orchestrator_common import (_as_bool, _as_float, _as_int, _as_str,
                                  _dedupe_by_host, _fetch_round, _head_tail,
                                  _host, condense_doc, content_quality_score,
                                  score_hit)
from .provider import SearchHit


async def build_web_block(
    query: str, k: int | None = None, per_url_timeout_s: float | None = None
) -> tuple[str | None, dict[str, Any]]:
    tel: dict[str, Any] = {"query": (query or "").strip()}
    cfg_k = int(k) if k is not None else _as_int("web_orch_default_k")
    total_char_budget = _as_int("web_orch_total_char_budget")
    per_doc_budget = _as_int("web_orch_per_doc_char_budget")
    max_parallel = _as_int("web_orch_max_parallel_fetch")
    overfetch_factor = _as_float("web_orch_overfetch_factor")
    overfetch_min_extra = _as_int("web_orch_overfetch_min_extra")
    enable_js_retry = _as_bool("web_orch_enable_js_retry")
    js_avg_q_thresh = _as_float("web_orch_js_retry_avg_q")
    js_low_q_thresh = _as_float("web_orch_js_retry_low_q")
    js_lowish_ratio = _as_float("web_orch_js_retry_lowish_ratio")
    js_timeout_add = _as_float("web_orch_js_retry_timeout_add")
    js_timeout_cap = _as_float("web_orch_js_retry_timeout_cap")
    js_parallel_delta = _as_int("web_orch_js_retry_parallel_delta")
    js_min_parallel = _as_int("web_orch_js_retry_min_parallel")
    header_tpl = _as_str("web_block_header")
    sep_str = _as_str("web_orch_block_separator")
    min_chunk_after = _as_int("web_orch_min_chunk_after_shrink")
    min_block_reserve = _as_int("web_orch_min_block_reserve")
    per_timeout = (
        float(per_url_timeout_s)
        if per_url_timeout_s is not None
        else _as_float("web_fetch_timeout_sec")
    )
    start_time = time.perf_counter()
    provider = BraveProvider()
    overfetch = max(cfg_k + overfetch_min_extra, int(round(cfg_k * overfetch_factor)))
    tel["search"] = {"requestedK": cfg_k, "overfetch": overfetch}
    t0 = time.perf_counter()
    try:
        hits: list[SearchHit] = await provider.search(
            query, k=overfetch, telemetry=tel["search"], xid=get_x_id()
        )
    except Exception as e:
        tel["error"] = {"stage": "search", "type": type(e).__name__, "msg": str(e)}
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        log.error("[web-block] (empty) due to search error: %s", tel["error"])
        return (None, tel)
    tel["search"]["elapsedSecTotal"] = round(time.perf_counter() - t0, 6)
    if not hits:
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        log.debug("[web-block] (empty) — no hits")
        return (None, tel)
    seen_urls = set()
    scored: list[tuple[int, SearchHit]] = []
    for h in hits:
        u = (h.url or "").strip()
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)
        s = score_hit(h, query)
        scored.append((s, h))
    tel["scoring"] = {"inputHits": len(hits), "scored": len(scored)}
    if not scored:
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        log.info("[web-block] (empty) — no scored hits")
        return (None, tel)
    prefetch = max(cfg_k * 2, cfg_k + 6)
    top_hits = _dedupe_by_host(scored, prefetch)
    tel["scoring"]["picked"] = len(top_hits)
    urls = [h.url for h in top_hits]
    meta = [(h.title or h.url, h.url) for h in top_hits]
    t_f = time.perf_counter()
    tel["fetch1"] = {}
    results = await _fetch_round(
        urls,
        meta,
        per_url_timeout_s=per_timeout,
        max_parallel=max_parallel,
        use_js=False,
        telemetry=tel["fetch1"],
    )
    tel["fetch1"]["roundSec"] = round(time.perf_counter() - t_f, 6)
    texts: list[tuple[str, str, str]] = []
    quality_scores: list[float] = []
    for original_url, res in results:
        if not res:
            continue
        final_url, status, text = res
        title = next((t for t, u in meta if u == original_url), final_url)
        qscore = content_quality_score(text or "")
        quality_scores.append(qscore)
        if text:
            texts.append((title, final_url, text))
    tel["fetch1"]["docs"] = {
        "ok": len(texts),
        "qAvg": sum(quality_scores) / len(quality_scores) if quality_scores else 0.0,
    }
    try_js = False
    if enable_js_retry and quality_scores:
        avg_q = sum(quality_scores) / len(quality_scores)
        lowish = sum(1 for q in quality_scores if q < js_low_q_thresh)
        if avg_q < js_avg_q_thresh or lowish / max(1, len(quality_scores)) >= js_lowish_ratio:
            try_js = True
        tel["jsRetry"] = {
            "considered": True,
            "triggered": try_js,
            "avgQ": round(avg_q, 4),
            "lowishRatio": round(lowish / max(1, len(quality_scores)) * 1.0, 4),
            "thresholds": {
                "avg": js_avg_q_thresh,
                "low": js_low_q_thresh,
                "ratio": js_lowish_ratio,
            },
        }
    else:
        tel["jsRetry"] = {"considered": bool(enable_js_retry), "triggered": False}
    if try_js:
        js_timeout = min(per_timeout + js_timeout_add, js_timeout_cap)
        js_parallel = max(js_min_parallel, max_parallel + js_parallel_delta)
        tel["fetch2"] = {"timeoutSec": js_timeout, "maxParallel": js_parallel}
        results_js = await _fetch_round(
            urls,
            meta,
            per_url_timeout_s=js_timeout,
            max_parallel=js_parallel,
            use_js=True,
            telemetry=tel["fetch2"],
        )
        texts_js: list[tuple[str, str, str]] = []
        for original_url, res in results_js:
            if not res:
                continue
            final_url, status, text = res
            title = next((t for t, u in meta if u == original_url), final_url)
            if text:
                texts_js.append((title, final_url, text))
        if texts_js:
            texts = texts_js
    if not texts:
        tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
        log.info("[web-block] (empty) — no fetched texts")
        return (None, tel)
    texts.sort(key=lambda t: content_quality_score(t[2]), reverse=True)
    by_host: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for title, url, text in texts:
        by_host[_host(url)].append((title, url, text))
    for h in by_host:
        by_host[h].sort(key=lambda x: content_quality_score(x[2]), reverse=True)
    hosts_ordered = sorted(
        by_host.keys(), key=lambda h: content_quality_score(by_host[h][0][2]), reverse=True
    )
    header = header_tpl.format(query=query)
    sep = sep_str
    available = max(min_block_reserve, total_char_budget - len(header) - len(sep))
    min_hosts = max(1, min(_as_int("web_orch_min_hosts"), len(hosts_ordered)))
    per_host_quota = max(min_chunk_after * 2, available // max(min_hosts, cfg_k))
    per_host_quota = min(per_host_quota, per_doc_budget)
    block_parts: list[str] = []
    used = 0
    included_hosts: list[str] = []
    for h in hosts_ordered:
        title, url, text = by_host[h][0]
        chunk = condense_doc(title, url, text, max_chars=per_host_quota)
        sep_len = len(sep) if block_parts else 0
        if used + sep_len + len(chunk) > available:
            rem = available - used - sep_len
            if rem > min_chunk_after:
                chunk = _head_tail(chunk, rem)
            else:
                break
        block_parts.append(chunk)
        included_hosts.append(h)
        used += sep_len + len(chunk)
        if len(included_hosts) >= min_hosts and used >= int(available * 0.66):
            break
    layer = 1
    while used < available:
        added_any = False
        for h in hosts_ordered:
            if layer >= len(by_host[h]):
                continue
            title, url, text = by_host[h][layer]
            sep_len = len(sep) if block_parts else 0
            chunk = condense_doc(title, url, text, max_chars=per_doc_budget)
            if used + sep_len + len(chunk) > available:
                rem = available - used - sep_len
                if rem <= min_chunk_after:
                    continue
                chunk = _head_tail(chunk, rem)
                if used + sep_len + len(chunk) > available:
                    continue
            block_parts.append(chunk)
            used += sep_len + len(chunk)
            added_any = True
            if used >= available:
                break
        if not added_any:
            break
        layer += 1
    body = sep.join(block_parts)
    block = f"{header}{sep}{body}" if body else header
    tel["assembly"] = {
        "chunksPicked": len(block_parts),
        "chars": len(block),
        "available": available,
        "headerChars": len(header),
        "hostsIncluded": len(included_hosts),
        "perHostQuota": per_host_quota,
    }
    tel["elapsedSec"] = round(time.perf_counter() - start_time, 6)
    log.info("[web-block] -------- BEGIN --------")
    log.info(block)
    log.info("[web-block] --------  END  --------")
    try:
        srcs = [{"title": t, "url": u} for t, u, _ in texts[:10]]
        log.info("[web-block] sources: %s", srcs)
    except Exception as _e:
        log.info("[web-block] sources: <unavailable> %s", str(_e))
    return (block, tel)
