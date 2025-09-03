# ===== aimodel/file_read/rag/retrieve_pipeline.py =====
from __future__ import annotations
from dataclasses import asdict
from typing import List, Tuple, Dict, Any, Optional
import time

from ..core.settings import SETTINGS
from .store import search_vectors
from .rerank import rerank_hits, cap_per_source, min_score_fraction
from .retrieve_common import (
    RagTelemetry,
    _embed_query,
    _primary_score,
    _dedupe_and_sort,
    _rescore_for_preferred_sources,
    _print_hits,
    build_block_for_hits,
    _nohit_block,
)

# --- NEW: safe preview helper (avoids backslashes inside f-string expressions)
def _mk_preview(text: Optional[str], limit: int = 400) -> str:
    t = (text or "")[:limit]
    return t.replace("\n", "\\n")

# Core builder with guarded rerank, min-frac → per-source cap, and no-guess behavior.
def _build_rag_block_core(
    query: str,
    *,
    session_id: str | None,
    k: int,
    session_only: bool,
    preferred_sources: Optional[List[str]] = None,
) -> Tuple[Optional[str], RagTelemetry]:
    tel = RagTelemetry(topKRequested=k, mode=("session-only" if session_only else "global"))
    q = (query or "").strip()
    print(f"[RAG SEARCH] q={q!r} session={session_id} k={k} session_only={session_only}")

    # Embed
    t0 = time.perf_counter()
    qvec = _embed_query(q)
    tel.embedSec = round(time.perf_counter() - t0, 6)
    if not qvec:
        print("[RAG SEARCH] no qvec")
        return None, tel

    d = len(qvec)

    # ANN search
    t1 = time.perf_counter()
    hits_chat = search_vectors(session_id, qvec, k, dim=d) or []
    tel.searchChatSec = round(time.perf_counter() - t1, 6)

    hits_glob: List[dict] = []
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
        print("[RAG SEARCH] no hits")
        return None, tel

    # Preference boost
    all_hits = _rescore_for_preferred_sources(all_hits, preferred_sources=preferred_sources)
    _print_hits("After preference boost", all_hits)

    # Safe copy BEFORE pruning
    pre_prune_hits = list(all_hits)

    # --- Rerank (guarded) ---
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
        print(f"[RAG] rerank error: {e}; skipping rerank")
        # keep pre-prune ordering
        pass

    tel.rerankSec = round(time.perf_counter() - t_rr, 6)
    tel.usedReranker = any("rerankScore" in h for h in all_hits)
    tel.keptAfterRerank = len(all_hits)
    _print_hits(f"After rerank (top_m={top_m})", all_hits)

    # --- Absolute rerank cutoff (optional) ---
    min_abs = SETTINGS.get("rag_min_abs_rerank")
    try:
        min_abs = float(min_abs) if min_abs not in (None, "", False) else None
    except Exception:
        min_abs = None
    if isinstance(min_abs, float):
        before = list(all_hits)
        all_hits = [h for h in all_hits if float(h.get("rerankScore") or -1e12) >= min_abs]
        if len(all_hits) != len(before):
            _print_hits(f"After abs rerank cutoff >= {min_abs}", all_hits)

    # --- Min-score fraction FIRST (robust) ---
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

    # --- Per-source cap AFTER min-frac ---
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

    # ===== No-guess SAFETY NET =====
    if not all_hits:
        # no fallback to best pre-prune — explicit no-hit signal
        tel.fallbackUsed = False
        print("[RAG] pruning yielded 0 hits; returning no-hit block")
        block = _nohit_block(q)
        tel.blockChars = len(block or "")
        preview = _mk_preview(block)
        print(f'[RAG BLOCK] chars={tel.blockChars} preview="{preview}"')
        print(f"[RAG BLOCK] kept: rerank={tel.keptAfterRerank} cap={tel.keptAfterCap} minFrac={tel.keptAfterMinFrac} fallback={tel.fallbackUsed}")
        return block, tel

    # Final selection
    t3 = time.perf_counter()
    hits_top = _dedupe_and_sort(all_hits, k=k)
    tel.dedupeSec = round(time.perf_counter() - t3, 6)
    _print_hits(f"Final top-k (k={k})", hits_top)

    # Build block
    t4 = time.perf_counter()
    block = build_block_for_hits(hits_top, preferred_sources=preferred_sources)
    tel.blockBuildSec = round(time.perf_counter() - t4, 6)
    tel.blockChars = len(block or "")
    preview = _mk_preview(block)
    print(f'[RAG BLOCK] chars={tel.blockChars} preview="{preview}"')
    print(f"[RAG BLOCK] kept: rerank={tel.keptAfterRerank} cap={tel.keptAfterCap} minFrac={tel.keptAfterMinFrac} fallback={tel.fallbackUsed}")

    return block, tel


# ========= Public wrappers =========

def build_rag_block(query: str, session_id: str | None = None, *, preferred_sources: Optional[List[str]] = None) -> str | None:
    if not bool(SETTINGS.get("rag_enabled")):
        return None
    k = int(SETTINGS.get("rag_top_k"))
    block, _ = _build_rag_block_core(query, session_id=session_id, k=k, session_only=False, preferred_sources=preferred_sources)
    return block


def build_rag_block_with_telemetry(query: str, session_id: str | None = None, *, preferred_sources: Optional[List[str]] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled")):
        return None, {}
    k = int(SETTINGS.get("rag_top_k"))
    block, tel = _build_rag_block_core(query, session_id=session_id, k=k, session_only=False, preferred_sources=preferred_sources)
    return block, asdict(tel)


def build_rag_block_session_only(query: str, session_id: Optional[str], *, k: Optional[int] = None, preferred_sources: Optional[List[str]] = None) -> Optional[str]:
    if not bool(SETTINGS.get("rag_enabled")):
        return None
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k"))
    block, _ = _build_rag_block_core(query, session_id=session_id, k=int(k), session_only=True, preferred_sources=preferred_sources)
    return block


def build_rag_block_session_only_with_telemetry(query: str, session_id: Optional[str], *, k: Optional[int] = None, preferred_sources: Optional[List[str]] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled")):
        return None, {}
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k"))
    block, tel = _build_rag_block_core(query, session_id=session_id, k=int(k), session_only=True, preferred_sources=preferred_sources)
    return block, asdict(tel)
