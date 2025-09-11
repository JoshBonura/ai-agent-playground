from __future__ import annotations

import logging

log = logging.getLogger(__name__)
import time
from dataclasses import asdict, dataclass
from typing import Any

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from .rerank import cap_per_source, min_score_fraction, rerank_hits
from .retrieve_tabular import make_rag_block_tabular
from .store import search_vectors

log = get_logger(__name__)

_EMBEDDER = None
_EMBEDDER_NAME = None
PRINT_MAX = 10


def _get_embedder():
    global _EMBEDDER, _EMBEDDER_NAME
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        log.info(f"[RAG] sentence_transformers unavailable: {e}")
        return (None, None)
    model_name = SETTINGS.get("rag_embedding_model")
    if not model_name:
        log.info("[RAG] no rag_embedding_model configured")
        return (None, None)
    if _EMBEDDER is None or _EMBEDDER_NAME != model_name:
        try:
            _EMBEDDER = SentenceTransformer(model_name)
            _EMBEDDER_NAME = model_name
        except Exception as e:
            log.error(f"[RAG] failed to load embedding model {model_name}: {e}")
            _EMBEDDER = None
            _EMBEDDER_NAME = None
    return (_EMBEDDER, _EMBEDDER_NAME)


def _embed_query(q: str) -> list[float]:
    q = (q or "").strip()
    if not q:
        return []
    model, _ = _get_embedder()
    if model is None:
        return []
    try:
        arr = model.encode([q], normalize_embeddings=True, convert_to_numpy=True)
        return arr[0].tolist()
    except Exception as e:
        log.error(f"[RAG] embedding encode failed: {e}")
        return []


def _primary_score(h: dict[str, Any]) -> float:
    s = h.get("rerankScore")
    if s is not None:
        try:
            return float(s)
        except Exception:
            pass
    try:
        return float(h.get("score") or 0.0)
    except Exception:
        return 0.0


def _dedupe_and_sort(hits: list[dict], *, k: int) -> list[dict]:
    hits_sorted = sorted(hits, key=_primary_score, reverse=True)
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for h in hits_sorted:
        kid = str(h.get("id") or "")
        key = (kid, "") if kid else (str(h.get("source") or ""), str(h.get("chunkIndex") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= k:
            break
    return out


def _default_header(h: dict[str, Any]) -> str:
    src = str(h.get("source") or "")
    idx = h.get("chunkIndex")
    return f"- {src} — chunk {idx}" if idx is not None else f"- {src}"


def _render_header(h: dict[str, Any]) -> str:
    return _default_header(h)


def make_rag_block_generic(hits: list[dict], *, max_chars: int) -> str:
    preamble = str(SETTINGS.get("rag_block_preamble") or "")
    preamble = preamble if not preamble or preamble.endswith(":") else preamble + ":"
    total_budget = int(SETTINGS.get("rag_total_char_budget"))
    lines = [preamble]
    used = len(lines[0]) + 1
    for h in hits:
        head = _render_header(h)
        body = (h.get("text") or "").strip()
        head_cost = len(head) + 1
        if used + head_cost >= total_budget:
            break
        lines.append(head)
        used += head_cost
        if body:
            snippet = body[:max_chars]
            snippet_line = "  " + snippet
            snippet_cost = len(snippet_line) + 1
            if used + snippet_cost > total_budget:
                remain = max(0, total_budget - used - 1)
                if remain > 0:
                    lines.append(("  " + snippet)[:remain])
                    used += remain + 1
                break
            lines.append(snippet_line)
            used += snippet_cost
    return "\n".join(lines)


@dataclass
class RagTelemetry:
    embedSec: float = 0.0
    searchChatSec: float = 0.0
    searchGlobalSec: float = 0.0
    hitsChat: int = 0
    hitsGlobal: int = 0
    rerankSec: float = 0.0
    usedReranker: bool = False
    keptAfterRerank: int = 0
    capPerSource: int = 0
    keptAfterCap: int = 0
    minScoreFrac: float = 0.0
    keptAfterMinFrac: int = 0
    fallbackUsed: bool = False
    dedupeSec: float = 0.0
    blockBuildSec: float = 0.0
    topKRequested: int = 0
    blockChars: int = 0
    mode: str = "global"


def _rescore_for_preferred_sources(
    hits: list[dict], preferred_sources: list[str] | None = None
) -> list[dict]:
    if not preferred_sources:
        return hits
    boost = float(SETTINGS.get("rag_new_upload_score_boost"))
    pref = set(s.strip().lower() for s in preferred_sources if s)
    out = []
    for h in hits:
        sc = float(h.get("score") or 0.0)
        src = str(h.get("source") or "").strip().lower()
        if src in pref:
            sc *= 1.0 + boost
        hh = dict(h)
        hh["score"] = sc
        out.append(hh)
    return out


def build_block_for_hits(hits_top: list[dict], preferred_sources: list[str] | None = None) -> str:
    block = make_rag_block_tabular(hits_top, preferred_sources=preferred_sources)
    if block is None:
        block = make_rag_block_generic(
            hits_top, max_chars=int(SETTINGS.get("rag_max_chars_per_chunk"))
        )
    return block or ""


def _fmt_hit(h: dict[str, Any]) -> str:
    return f"id={h.get('id')!s} src={h.get('source')!s} chunk={h.get('chunkIndex')!s} row={h.get('row')!s} score={h.get('score')!s} rerank={h.get('rerankScore')!s}"


def _print_hits(label: str, hits: list[dict[str, Any]], limit: int = PRINT_MAX) -> None:
    log.debug(f"[RAG DEBUG] {label}: count={len(hits)}")
    for i, h in enumerate(hits[:limit]):
        log.debug(f"[RAG DEBUG]   {i + 1:02d}: {_fmt_hit(h)}")
    if len(hits) > limit:
        log.debug(f"[RAG DEBUG]   … (+{len(hits) - limit} more)")


def _build_rag_block_core(
    query: str,
    *,
    session_id: str | None,
    k: int,
    session_only: bool,
    preferred_sources: list[str] | None = None,
) -> tuple[str | None, RagTelemetry]:
    tel = RagTelemetry(topKRequested=k, mode="session-only" if session_only else "global")
    q = (query or "").strip()
    log.debug(f"[RAG SEARCH] q={q!r} session={session_id} k={k} session_only={session_only}")
    t0 = time.perf_counter()
    qvec = _embed_query(q)
    tel.embedSec = round(time.perf_counter() - t0, 6)
    if not qvec:
        log.debug("[RAG SEARCH] no qvec")
        return (None, tel)
    d = len(qvec)
    t1 = time.perf_counter()
    hits_chat = search_vectors(session_id, qvec, k, dim=d) or []
    tel.searchChatSec = round(time.perf_counter() - t1, 6)
    hits_glob: list[dict] = []
    if not session_only:
        t2 = time.perf_counter()
        hits_glob = search_vectors(None, qvec, k, dim=d) or []
        tel.searchGlobalSec = round(time.perf_counter() - t2, 6)
    tel.hitsChat = len(hits_chat)
    tel.hitsGlobal = len(hits_glob)
    _print_hits("ANN hits (chat)", hits_chat)
    if not session_only:
        _print_hits("ANN hits (global)", hits_glob)
    all_hits = hits_chat + ([] if session_only else hits_glob)
    if not all_hits:
        log.debug("[RAG SEARCH] no hits")
        return (None, tel)
    all_hits = _rescore_for_preferred_sources(all_hits, preferred_sources=preferred_sources)
    _print_hits("After preference boost", all_hits)
    pre_prune_hits = list(all_hits)
    t_rr = time.perf_counter()
    top_m_cfg = SETTINGS.get("rag_rerank_top_m")
    try:
        top_m = int(top_m_cfg) if top_m_cfg not in (None, "", False) else None
    except Exception:
        top_m = None
    if isinstance(top_m, int):
        top_m = max(1, min(top_m, len(all_hits)))
    try:
        all_hits = rerank_hits(q, all_hits, top_m=top_m)
    except Exception as e:
        log.error(f"[RAG] rerank error: {e}; skipping rerank")
        pass
    tel.rerankSec = round(time.perf_counter() - t_rr, 6)
    tel.usedReranker = any("rerankScore" in h for h in all_hits)
    tel.keptAfterRerank = len(all_hits)
    _print_hits(f"After rerank (top_m={top_m})", all_hits)
    frac_cfg = SETTINGS.get("rag_min_score_frac")
    try:
        frac = float(frac_cfg) if frac_cfg not in (None, "", False) else None
    except Exception:
        frac = None
    tel.minScoreFrac = float(frac) if isinstance(frac, (int, float)) else 0.0
    if isinstance(frac, (int, float)):
        key = "rerankScore" if any("rerankScore" in h for h in all_hits) else "score"
        before = list(all_hits)
        all_hits = min_score_fraction(all_hits, key, float(frac))
        _print_hits(f"After minScoreFrac={frac} on key={key}", all_hits)
        dropped = [h for h in before if h not in all_hits]
        if dropped:
            _print_hits("Dropped by minScoreFrac", dropped)
    tel.keptAfterMinFrac = len(all_hits)
    cap_cfg = SETTINGS.get("rag_per_source_cap")
    try:
        cap_val = int(cap_cfg) if cap_cfg not in (None, "", False) else 0
    except Exception:
        cap_val = 0
    tel.capPerSource = cap_val
    if cap_val and cap_val > 0:
        before = list(all_hits)
        all_hits = cap_per_source(all_hits, cap_val)
        _print_hits(f"After per-source cap={cap_val}", all_hits)
        dropped = [h for h in before if h not in all_hits]
        if dropped:
            _print_hits("Dropped by per-source cap", dropped)
    tel.keptAfterCap = len(all_hits)
    if not all_hits:
        best = sorted(pre_prune_hits, key=_primary_score, reverse=True)[:1]
        all_hits = best
        tel.fallbackUsed = True
        log.info("[RAG] pruning yielded 0 hits; falling back to best pre-prune hit")
        _print_hits("Fallback best pre-prune", all_hits)
    t3 = time.perf_counter()
    hits_top = _dedupe_and_sort(all_hits, k=k)
    tel.dedupeSec = round(time.perf_counter() - t3, 6)
    _print_hits(f"Final top-k (k={k})", hits_top)
    t4 = time.perf_counter()
    block = build_block_for_hits(hits_top, preferred_sources=preferred_sources)
    tel.blockBuildSec = round(time.perf_counter() - t4, 6)
    tel.blockChars = len(block or "")
    preview = (block or "")[:400].replace("\n", "\\n")
    log.debug(f'[RAG BLOCK] chars={tel.blockChars} preview="{preview}"')
    log.debug(
        f"[RAG BLOCK] kept: rerank={tel.keptAfterRerank} cap={tel.keptAfterCap} minFrac={tel.keptAfterMinFrac} fallback={tel.fallbackUsed}"
    )
    return (block, tel)


def build_rag_block(
    query: str, session_id: str | None = None, *, preferred_sources: list[str] | None = None
) -> str | None:
    if not bool(SETTINGS.get("rag_enabled")):
        return None
    k = int(SETTINGS.get("rag_top_k"))
    block, _ = _build_rag_block_core(
        query, session_id=session_id, k=k, session_only=False, preferred_sources=preferred_sources
    )
    return block


def build_rag_block_with_telemetry(
    query: str, session_id: str | None = None, *, preferred_sources: list[str] | None = None
) -> tuple[str | None, dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled")):
        return (None, {})
    k = int(SETTINGS.get("rag_top_k"))
    block, tel = _build_rag_block_core(
        query, session_id=session_id, k=k, session_only=False, preferred_sources=preferred_sources
    )
    return (block, asdict(tel))


def build_rag_block_session_only(
    query: str,
    session_id: str | None,
    *,
    k: int | None = None,
    preferred_sources: list[str] | None = None,
) -> str | None:
    if not bool(SETTINGS.get("rag_enabled")):
        return None
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k"))
    block, _ = _build_rag_block_core(
        query,
        session_id=session_id,
        k=int(k),
        session_only=True,
        preferred_sources=preferred_sources,
    )
    return block


def build_rag_block_session_only_with_telemetry(
    query: str,
    session_id: str | None,
    *,
    k: int | None = None,
    preferred_sources: list[str] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled")):
        return (None, {})
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k"))
    block, tel = _build_rag_block_core(
        query,
        session_id=session_id,
        k=int(k),
        session_only=True,
        preferred_sources=preferred_sources,
    )
    return (block, asdict(tel))
