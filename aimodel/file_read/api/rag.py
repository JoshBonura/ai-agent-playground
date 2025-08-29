# aimodel/file_read/api/rag.py
from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, List
import numpy as np
from sentence_transformers import SentenceTransformer
from threading import RLock

from ..rag.schemas import SearchReq, SearchHit
from ..rag.ingest import sniff_and_extract, chunk_text, build_metas
from ..rag.store import add_vectors, search_vectors

router = APIRouter(prefix="/api/rag", tags=["rag"])

# ---- embedding model (sync, cached) ----
_st_model: SentenceTransformer | None = None
_st_lock = RLock()

def _get_st_model() -> SentenceTransformer:
    global _st_model
    if _st_model is None:
        with _st_lock:
            if _st_model is None:
                print("[RAG EMBED] loading e5-small-v2… (one-time)")
                _st_model = SentenceTransformer("intfloat/e5-small-v2")
                print("[RAG EMBED] model ready")
    return _st_model

def _embed(texts: List[str]) -> np.ndarray:
    model = _get_st_model()
    arr = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return arr.astype("float32")

@router.post("/upload")
async def upload_doc(sessionId: Optional[str] = Form(default=None), file: UploadFile = File(...)):
    print(f"[RAG UPLOAD] sessionId={sessionId}, filename={file.filename}, content_type={file.content_type}")

    data = await file.read()
    print(f"[RAG UPLOAD] file size={len(data)} bytes")

    text, mime = sniff_and_extract(file.filename, data)
    print(f"[RAG UPLOAD] extracted mime={mime}, text_len={len(text)}")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty/unsupported file")

    chunks = chunk_text(text, {"mime": mime})
    print(f"[RAG UPLOAD] chunk_count={len(chunks)}")

    metas = build_metas(sessionId, file.filename, chunks, size=len(data))
    embeds = _embed([c.text for c in chunks])
    print(f"[RAG UPLOAD] embed_shape={embeds.shape}")

    add_vectors(sessionId, embeds, metas, dim=embeds.shape[1])
    return {"ok": True, "added": len(chunks)}

@router.post("/search")
async def search(req: SearchReq):
    q = req.query.strip()
    if not q:
        return {"hits": []}
    qv = np.array(_embed([q])[0], dtype="float32")
    chat_hits = search_vectors(req.sessionId, qv, req.kChat, dim=qv.shape[0])
    global_hits = search_vectors(None, qv, req.kGlobal, dim=qv.shape[0])
    from ..rag.search import merge_chat_first
    fused = merge_chat_first(chat_hits, global_hits, alpha=req.hybrid_alpha)
    out: List[SearchHit] = []
    for r in fused:
        out.append(SearchHit(
            id=r["id"], text=r["text"], score=float(r["score"]),
            source=r.get("source"), title=r.get("title"), sessionId=r.get("sessionId")
        ))
    return {"hits": [h.model_dump() for h in out]}

@router.get("/list")
async def list_items(sessionId: Optional[str] = None, k: int = 20):
    """
    Debug: show a lightweight list of stored chunks for a session (or global if sessionId is None).
    Returns id/source/score and a short text preview so you can verify ingestion.
    """
    qv = np.array(_embed(["list"])[0], dtype="float32")
    hits = search_vectors(sessionId, qv, topk=k, dim=qv.shape[0])

    items = []
    for h in hits:
        txt = (h.get("text") or "")
        items.append({
            "id": h.get("id"),
            "sessionId": h.get("sessionId"),
            "source": h.get("source"),
            "title": h.get("title"),
            "score": float(h.get("score", 0.0)),
            "text": txt,
        })
    print(f"[RAG LIST] sessionId={sessionId} k={k} -> {len(items)} items")
    return {"items": items}

@router.get("/dump")
async def dump_items(sessionId: Optional[str] = None, k: int = 50):
    """
    Debug: return full texts of top-k chunks (be careful: can be large).
    Useful to confirm exact strings that were indexed.
    """
    qv = np.array(_embed(["dump"])[0], dtype="float32")
    hits = search_vectors(sessionId, qv, k=k, dim=qv.shape[0])

    chunks = []
    for h in hits:
        chunks.append({
            "id": h.get("id"),
            "sessionId": h.get("sessionId"),
            "source": h.get("source"),
            "title": h.get("title"),
            "score": float(h.get("score", 0.0)),
            "text": h.get("text") or "",
        })
    print(f"[RAG DUMP] sessionId={sessionId} k={k} -> {len(chunks)} items")
    return {"chunks": chunks}
