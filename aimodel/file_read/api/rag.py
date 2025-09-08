# aimodel/file_read/api/rag.py
from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, List, Dict
import numpy as np
from sentence_transformers import SentenceTransformer
from threading import RLock
from ..rag.uploads import list_sources as rag_list_sources, hard_delete_source
from ..rag.schemas import SearchReq, SearchHit
from ..rag.ingest import sniff_and_extract, chunk_text, build_metas
from ..rag.store import add_vectors, search_vectors

router = APIRouter(prefix="/api/rag", tags=["rag"])

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
    q = (req.query or "").strip()
    if not q:
        return {"hits": []}

    qv = _embed([q])[0]
    chat_hits = search_vectors(req.sessionId, qv, req.kChat, dim=qv.shape[0]) if req.kChat else []
    global_hits = search_vectors(None, qv, req.kGlobal, dim=qv.shape[0]) if req.kGlobal else []

    fused = sorted(chat_hits + global_hits, key=lambda r: r["score"], reverse=True)

    out: List[SearchHit] = []
    for r in fused:
        out.append(SearchHit(
            id=r["id"],
            text=r["text"],
            score=float(r["score"]),
            source=r.get("source"),
            title=r.get("title"),
            sessionId=r.get("sessionId"),
        ))
    return {"hits": [h.model_dump() for h in out]}

@router.get("/list")
async def list_items(sessionId: Optional[str] = None, k: int = 20):
    qv = _embed(["list"])[0]
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
    qv = _embed(["dump"])[0]
    hits = search_vectors(sessionId, qv, topk=k, dim=qv.shape[0])

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

@router.get("/uploads")
async def api_list_uploads(sessionId: Optional[str] = None, scope: str = "all"):
    include_global = scope != "session"
    return {"uploads": rag_list_sources(sessionId, include_global=include_global)}

@router.post("/uploads/delete-hard")
async def api_delete_upload_hard(body: dict[str, str]):
    source = (body.get("source") or "").strip()
    session_id = (body.get("sessionId") or None)
    if not source:
        return {"error": "source required"}

    out = hard_delete_source(source, session_id=session_id, embedder=_embed)
    return out
