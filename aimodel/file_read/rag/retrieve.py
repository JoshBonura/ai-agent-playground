# ===== aimodel/file_read/rag/retrieve.py =====
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple, Dict, Any
import time

from ..core.settings import SETTINGS
from .store import search_vectors

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

def _dedupe_and_sort(hits: List[dict], *, k: int) -> List[dict]:
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

def _first_nonempty(*vals: Any) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _excelish_header(h: Dict[str, Any]) -> Optional[str]:
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
            pass
        out.append(ln)
        used += need
    return "\n".join(out)

def make_rag_block(hits: List[dict], *, max_chars: int = 800) -> str:
    lines = ["Local knowledge:"]
    total_budget = int(SETTINGS.get("rag_total_char_budget", 2200))
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
    dedupeSec: float = 0.0
    blockBuildSec: float = 0.0
    topKRequested: int = 0
    blockChars: int = 0
    mode: str = "global"

def _build_rag_block_core(query: str, *, session_id: str | None, k: int, session_only: bool) -> Tuple[Optional[str], RagTelemetry]:
    tel = RagTelemetry(topKRequested=k, mode=("session-only" if session_only else "global"))
    q = (query or "").strip()
    print(f"[RAG SEARCH] q={q!r} session={session_id} k={k} session_only={session_only}")

    t0 = time.perf_counter()
    qvec = _embed_query(q)
    tel.embedSec = round(time.perf_counter() - t0, 6)

    if not qvec:
        print("[RAG SEARCH] no qvec")
        return None, tel

    d = len(qvec)

    hits_chat: List[dict] = []
    hits_glob: List[dict] = []

    t1 = time.perf_counter()
    hits_chat = search_vectors(session_id, qvec, k, dim=d) or []
    tel.searchChatSec = round(time.perf_counter() - t1, 6)

    if not session_only:
        t2 = time.perf_counter()
        hits_glob = search_vectors(None, qvec, k, dim=d) or []
        tel.searchGlobalSec = round(time.perf_counter() - t2, 6)

    tel.hitsChat = len(hits_chat)
    tel.hitsGlobal = len(hits_glob)

    all_hits = hits_chat + ([] if session_only else hits_glob)

    if not all_hits:
        print("[RAG SEARCH] no hits")
        return None, tel

    t3 = time.perf_counter()
    hits_top = _dedupe_and_sort(all_hits, k=k)
    tel.dedupeSec = round(time.perf_counter() - t3, 6)

    t4 = time.perf_counter()
    block = make_rag_block(
        hits_top,
        max_chars=int(SETTINGS.get("rag_max_chars_per_chunk", 800)),
    )
    tel.blockBuildSec = round(time.perf_counter() - t4, 6)
    tel.blockChars = len(block or "")
    print(f"[RAG BLOCK] chars={tel.blockChars}")
    return block, tel

def build_rag_block(query: str, session_id: str | None = None) -> str | None:
    if not bool(SETTINGS.get("rag_enabled", True)):
        return None
    k = int(SETTINGS.get("rag_top_k", 4))
    block, _ = _build_rag_block_core(query, session_id=session_id, k=k, session_only=False)
    return block

def build_rag_block_with_telemetry(query: str, session_id: str | None = None) -> Tuple[Optional[str], Dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled", True)):
        return None, {}
    k = int(SETTINGS.get("rag_top_k", 4))
    block, tel = _build_rag_block_core(query, session_id=session_id, k=k, session_only=False)
    return block, asdict(tel)

def build_rag_block_session_only(query: str, session_id: Optional[str], *, k: Optional[int] = None) -> Optional[str]:
    if not bool(SETTINGS.get("rag_enabled", True)):
        return None
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k", SETTINGS.get("rag_top_k", 4)))
    block, _ = _build_rag_block_core(query, session_id=session_id, k=int(k), session_only=True)
    return block

def build_rag_block_session_only_with_telemetry(query: str, session_id: Optional[str], *, k: Optional[int] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    if not bool(SETTINGS.get("rag_enabled", True)):
        return None, {}
    if k is None:
        k = int(SETTINGS.get("attachments_retrieve_top_k", SETTINGS.get("rag_top_k", 4)))
    block, tel = _build_rag_block_core(query, session_id=session_id, k=int(k), session_only=True)
    return block, asdict(tel)
