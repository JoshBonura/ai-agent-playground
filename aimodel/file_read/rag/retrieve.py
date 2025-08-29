from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Any
from ..core.settings import SETTINGS
from .store import search_vectors

# -------- Embedding backend (cached) -----------------------------------------

_EMBEDDER = None
_EMBEDDER_NAME = None

def _get_embedder():
    global _EMBEDDER, _EMBEDDER_NAME
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        print(f"[RAG] sentence_transformers unavailable: {e}")
        return None, None

    model_name = str(SETTINGS.get("rag_embedding_model", "intfloat/e5-small-v2"))
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

# -------- Hit handling --------------------------------------------------------

def _dedupe_and_sort(hits: List[dict], *, k: int) -> List[dict]:
    """
    Sort by score desc, then de-dupe by a stable key.
    Prefer (id) if present, else (source, chunkIndex).
    """
    hits_sorted = sorted(hits, key=lambda h: float(h.get("score", 0.0)), reverse=True)
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

# -------- Pretty block rendering ---------------------------------------------

def _first_nonempty(*vals: Any) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _excelish_header(h: Dict[str, Any]) -> Optional[str]:
    """
    If this hit came from Excel row ingestion, surface sheet/table/row in the header.
    We look both at top-level keys and inside 'meta' to be robust against your store schema.
    """
    meta = h.get("meta") or {}
    mime = _first_nonempty(h.get("mime"), meta.get("mime"))
    if mime not in {"text/excel+row", "text/excel+lines", "text/excel+cells"}:
        return None

    src = _first_nonempty(h.get("source"), meta.get("source"))
    sheet = _first_nonempty(h.get("sheet"), meta.get("sheet"))
    table = _first_nonempty(h.get("table"), meta.get("table"))
    row_id = _first_nonempty(h.get("row_id"), meta.get("row_id"))
    idx = _first_nonempty(str(h.get("chunkIndex") or ""), str(meta.get("chunkIndex") or ""))

    parts = [src]
    if sheet:
        parts.append(f"{sheet}")
    if table:
        parts.append(f"tbl {table}")
    if row_id:
        parts.append(f"row {row_id}")
    elif idx:
        parts.append(f"chunk {idx}")

    label = " — ".join(parts) if parts else None
    return f"- {label}" if label else None

def _default_header(h: Dict[str, Any]) -> str:
    src = str(h.get("source") or "")
    idx = h.get("chunkIndex")
    return f"- {src} — chunk {idx}" if idx is not None else f"- {src}"

def _render_header(h: Dict[str, Any]) -> str:
    eh = _excelish_header(h)
    return eh if eh else _default_header(h)

def _trim_to_budget(lines: List[str], total_budget: int) -> str:
    out = []
    used = 0
    for i, ln in enumerate(lines):
        need = len(ln) + (1 if i > 0 else 0)
        if used + need > total_budget:
            break
        if i > 0:
            out.append("") if False else None  # no-op; kept for readability
        out.append(ln)
        used += need
    return "\n".join(out)

def make_rag_block(hits: List[dict], *, max_chars: int = 800) -> str:
    """
    Formats hits into a compact, model-friendly block.
    Shows Excel row context when available. Obeys total budget.
    """
    lines = ["Local knowledge:"]
    total_budget = int(SETTINGS.get("rag_total_char_budget", 2200))
    used = len(lines[0]) + 1  # header + newline

    for h in hits:
        head = _render_header(h)
        body = (h.get("text") or "").strip()

        # header
        head_cost = len(head) + 1
        if used + head_cost >= total_budget:
            break
        lines.append(head)
        used += head_cost

        # body/snippet
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

# -------- Public entry --------------------------------------------------------

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
        max_chars=int(SETTINGS.get("rag_max_chars_per_chunk", 800)),
    )
    print(f"[RAG BLOCK] chars={len(block)}")
    return block
