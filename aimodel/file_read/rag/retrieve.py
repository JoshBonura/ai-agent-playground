from __future__ import annotations
from typing import List, Optional, Tuple
from ..core.settings import SETTINGS
from .store import search_vectors

def _embed_query(q: str) -> List[float]:
    q = (q or "").strip()
    if not q:
        return []
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("intfloat/e5-small-v2")
        arr = model.encode([q], normalize_embeddings=True, convert_to_numpy=True)
        return arr[0].tolist()
    except Exception as e:
        print(f"[RAG] embedding backend failed: {e}")
        return []

def _dedupe_and_sort(hits: List[dict], *, k: int) -> List[dict]:
    # sort by score desc, then stable de-dupe by (source, chunkIndex)
    hits_sorted = sorted(hits, key=lambda h: float(h.get("score", 0.0)), reverse=True)
    seen: set[Tuple[str, str]] = set()
    out: List[dict] = []
    for h in hits_sorted:
        key = (str(h.get("source") or ""), str(h.get("chunkIndex") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= k:
            break
    return out

def make_rag_block(hits: List[dict], *, max_chars: int = 800) -> str:
    lines = ["Local knowledge:"]
    total_budget = int(SETTINGS.get("rag_total_char_budget", 2200))  # NEW
    used = 0

    for h in hits:
        src = h.get("source") or ""
        idx = h.get("chunkIndex")
        head = f"- {src} — chunk {idx}" if idx is not None else f"- {src}"
        body = (h.get("text") or "").strip()

        # header + newline cost
        head_cost = len(head) + 1
        if used + head_cost >= total_budget:
            break
        lines.append(head)
        used += head_cost

        if body:
            snippet = body[:max_chars]
            snippet_cost = len(snippet) + 1 + 2  # indent + newline
            if used + snippet_cost > total_budget:
                remain = max(0, total_budget - used - 3)
                if remain > 0:
                    lines.append("  " + snippet[:remain])
                    used += 2 + remain
                break
            lines.append("  " + snippet)
            used += snippet_cost

    return "\n".join(lines)

def build_rag_block(query: str, session_id: str | None = None) -> str | None:
    if not bool(SETTINGS.get("rag_enabled", True)):
        return None
    k = int(SETTINGS.get("rag_top_k", 4))

    q = (query or "").strip()
    print(f"[RAG SEARCH] q={q!r} session={session_id} k={k}")
    qvec = _embed_query(q)
    if not qvec:
        print("[RAG SEARCH] no qvec")
        return None

    # Pull hits from session scope and global scope
    d = len(qvec)
    hits_chat = search_vectors(session_id, qvec, k, dim=d) or []
    hits_glob = search_vectors(None,       qvec, k, dim=d) or []
    hits = hits_chat + hits_glob

    print(f"[RAG SEARCH] hits={len(hits)}")
    if not hits:
        return None

    hits_top = _dedupe_and_sort(hits, k=k)
    block = make_rag_block(
    hits_top,
    max_chars=int(SETTINGS.get("rag_max_chars_per_chunk", 800))  # ← use RAG knob
)
    print(f"[RAG BLOCK] chars={len(block)}")
    return block


