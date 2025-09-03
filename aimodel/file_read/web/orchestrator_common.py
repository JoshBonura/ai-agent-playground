# DEBUG prints added with prefix [WEB][ORCH][COMMON]
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urlparse
import re

from ..core.settings import SETTINGS
from .provider import SearchHit
from .fetch import fetch_many

def _req(key: str):
    return SETTINGS[key]

def _as_int(key: str) -> int: return int(_req(key))
def _as_float(key: str) -> float: return float(_req(key))
def _as_bool(key: str) -> bool: return bool(_req(key))
def _as_str(key: str) -> str:
    v = _req(key)
    return "" if v is None else str(v)

def _clean_ws(s: str) -> str:
    return " ".join((s or "").split())

def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    pref = _as_str("web_orch_www_prefix")
    return h[len(pref):] if pref and h.startswith(pref) else h

def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"\w+", (s or "").lower()) if t]

def _head_tail(text: str, max_chars: int) -> str:
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return _clean_ws(text)
    head_frac      = _as_float("web_orch_head_fraction")
    tail_min_chars = _as_int("web_orch_tail_min_chars")
    ellipsis       = _as_str("web_orch_ellipsis")
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

def score_hit(hit: SearchHit, query: str) -> int:
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
        return 0.1 * length_score
    uniq = len(set(toks))
    diversity = uniq / max(1.0, float(len(toks)))
    pen = 0.0
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

async def _fetch_round(
    urls: List[str],
    meta: List[Tuple[str, str]],
    per_url_timeout_s: float,
    max_parallel: int,
    use_js: bool = False,
    telemetry: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Optional[Tuple[str, int, str]]]]:
    fetch_fn = fetch_many
    if use_js:
        try:
            from . import fetch as _fetch_mod  # type: ignore
            fetch_fn = getattr(_fetch_mod, "fetch_many_js", fetch_many)
        except Exception:
            fetch_fn = fetch_many
    cap_mult        = _as_float("web_orch_fetch_cap_multiplier")
    per_doc_budget  = _as_int("web_orch_per_doc_char_budget")
    fetch_max_chars = _as_int("web_fetch_max_chars")
    per_doc_cap     = min(int(per_doc_budget * cap_mult), fetch_max_chars)

    print(f"[WEB][ORCH][COMMON] _fetch_round use_js={use_js} urls={len(urls)} per_timeout={per_url_timeout_s} max_parallel={max_parallel} per_doc_cap={per_doc_cap}")

    results = await fetch_fn(
        urls,
        per_timeout_s=per_url_timeout_s,
        cap_chars=per_doc_cap,
        max_parallel=max_parallel,
        telemetry=telemetry,
    )

    ok = sum(1 for _, r in results if r)
    print(f"[WEB][ORCH][COMMON] _fetch_round done ok={ok}/{len(results)}")
    return results
