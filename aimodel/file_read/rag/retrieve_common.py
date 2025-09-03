# aimodel/file_read/rag/retrieve_common.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import time

from ..core.settings import SETTINGS
from .retrieve_tabular import make_rag_block_tabular

_EMBEDDER = None
_EMBEDDER_NAME = None
PRINT_MAX = 10  # cap how many hits we dump at each stage


# ========= Embedding helpers =========

def _get_embedder():
    global _EMBEDDER, _EMBEDDER_NAME
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        print(f"[RAG] sentence_transformers unavailable: {e}")
        return None, None

    model_name = SETTINGS.get("rag_embedding_model")
    if not model_name:
        print("[RAG] no rag_embedding_model configured")
        return None, None

    if _EMBEDDER is None or _EMBEDDER_NAME != model_name:
        try:
            _EMBEDDER = SentenceTransformer(model_name)
            _EMBEDDER_NAME = model_name
        except Exception as e:
            print(f"[RAG] failed to load embedding model {model_name}: {e}")
            _EMBEDDER = None
            _EMBEDDER_NAME = None
    return _EMBEDDER, _EMBEDDER_NAME


def _embed_query(q: str) -> List[float]:
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
        print(f"[RAG] embedding encode failed: {e}")
        return []


# ========= Scoring / ordering =========

def _primary_score(h: Dict[str, Any]) -> float:
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


def _dedupe_and_sort(hits: List[dict], *, k: int) -> List[dict]:
    hits_sorted = sorted(hits, key=_primary_score, reverse=True)
    seen: set[Tuple[str, str]] = set()
    out: List[dict] = []
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


# ========= Block rendering =========

def _default_header(h: Dict[str, Any]) -> str:
    src = str(h.get("source") or "")
    idx = h.get("chunkIndex")
    return f"- {src} — chunk {idx}" if idx is not None else f"- {src}"


def _render_header(h: Dict[str, Any]) -> str:
    return _default_header(h)


def make_rag_block_generic(hits: List[dict], *, max_chars: int) -> str:
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


def build_block_for_hits(hits_top: List[dict], preferred_sources: Optional[List[str]] = None) -> str:
    block = make_rag_block_tabular(hits_top, preferred_sources=preferred_sources)
    if block is None:
        block = make_rag_block_generic(
            hits_top,
            max_chars=int(SETTINGS.get("rag_max_chars_per_chunk")),
        )
    return block or ""


# ========= Preference boost / debug =========

def _rescore_for_preferred_sources(hits: List[dict], preferred_sources: Optional[List[str]] = None) -> List[dict]:
    if not preferred_sources:
        return hits
    boost = float(SETTINGS.get("rag_new_upload_score_boost"))
    pref = set(s.strip().lower() for s in preferred_sources if s)
    out = []
    for h in hits:
        sc = float(h.get("score") or 0.0)
        src = str(h.get("source") or "").strip().lower()
        if src in pref:
            sc *= (1.0 + boost)
        hh = dict(h)
        hh["score"] = sc
        out.append(hh)
    return out


def _fmt_hit(h: Dict[str, Any]) -> str:
    return (
        f"id={h.get('id')!s} src={h.get('source')!s} "
        f"chunk={h.get('chunkIndex')!s} row={h.get('row')!s} "
        f"score={h.get('score')!s} rerank={h.get('rerankScore')!s}"
    )


def _print_hits(label: str, hits: List[Dict[str, Any]], limit: int = PRINT_MAX) -> None:
    print(f"[RAG DEBUG] {label}: count={len(hits)}")
    for i, h in enumerate(hits[:limit]):
        print(f"[RAG DEBUG]   {i+1:02d}: {_fmt_hit(h)}")
    if len(hits) > limit:
        print(f"[RAG DEBUG]   … (+{len(hits)-limit} more)")


def _nohit_block(q: str) -> str:
    preamble = str(SETTINGS.get("rag_block_preamble") or "Local knowledge")
    preamble = preamble if preamble.endswith(":") else preamble + ":"
    msg = str(SETTINGS.get("rag_nohit_message") or "⛔ No relevant local entries found for this query. Do not guess.")
    if q:
        return f"{preamble}\n- {msg}\n- query={q!r}"
    return f"{preamble}\n- {msg}"


# ========= Telemetry =========

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
