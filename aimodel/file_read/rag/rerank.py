from __future__ import annotations
from typing import List, Dict, Optional
from ..core.settings import SETTINGS

_RERANKER = None
_RERANKER_NAME = None

def _load_reranker():
    global _RERANKER, _RERANKER_NAME
    model_name = SETTINGS.get("rag_rerank_model")
    if not model_name:
        return None
    if _RERANKER is not None and _RERANKER_NAME == model_name:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(model_name)
        _RERANKER_NAME = model_name
        return _RERANKER
    except Exception as e:
        print(f"[RAG RERANK] failed to load reranker {model_name}: {e}")
        _RERANKER = None
        _RERANKER_NAME = None
        return None

def rerank_hits(query: str, hits: List[dict], *, top_m: Optional[int] = None) -> List[dict]:
    if not hits:
        return hits
    model = _load_reranker()
    if model is None:
        return hits

    pairs = [(query, (h.get("text") or "")) for h in hits]
    try:
        scores = model.predict(pairs)
    except Exception as e:
        print(f"[RAG RERANK] predict failed: {e}")
        return hits

    out: List[dict] = []
    for h, s in zip(hits, scores):
        hh = dict(h)
        hh["rerankScore"] = float(s)
        out.append(hh)

    out.sort(key=lambda x: x.get("rerankScore", 0.0), reverse=True)
    if isinstance(top_m, int) and top_m > 0:
        out = out[:top_m]
    return out

def cap_per_source(hits: List[dict], per_source_cap: int) -> List[dict]:
    if per_source_cap is None or per_source_cap <= 0:
        return hits
    bucket: dict[str, int] = {}
    out: List[dict] = []
    for h in hits:
        src = str(h.get("source") or "")
        seen = bucket.get(src, 0)
        if seen < per_source_cap:
            out.append(h)
            bucket[src] = seen + 1
    return out

def min_score_fraction(hits: List[Dict], key: str, frac: float) -> List[Dict]:
    if not hits:
        return hits
    vals = []
    for h in hits:
        try:
            v = float(h.get(key) or 0.0)
        except Exception:
            v = 0.0
        vals.append(v)

    s_min = min(vals)
    s_max = max(vals)
    if s_max == s_min:
        return hits

    kept = []
    for h, v in zip(hits, vals):
        norm = (v - s_min) / (s_max - s_min)
        if norm >= float(frac):
            kept.append(h)
    return kept
