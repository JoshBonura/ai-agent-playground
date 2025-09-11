from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
from threading import RLock

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sentence_transformers import SentenceTransformer

from ..rag.ingest import build_metas, chunk_text, sniff_and_extract
from ..rag.schemas import SearchHit, SearchReq
from ..rag.store import add_vectors, search_vectors
from ..rag.uploads import hard_delete_source
from ..rag.uploads import list_sources as rag_list_sources

router = APIRouter(prefix="/api/rag", tags=["rag"])
_st_model: SentenceTransformer | None = None
_st_lock = RLock()


def _get_st_model() -> SentenceTransformer:
    global _st_model
    if _st_model is None:
        with _st_lock:
            if _st_model is None:
                log.info("[RAG EMBED] loading e5-small-v2… (one-time)")
                _st_model = SentenceTransformer("intfloat/e5-small-v2")
                log.info("[RAG EMBED] model ready")
    return _st_model


def _embed(texts: list[str]) -> np.ndarray:
    model = _get_st_model()
    arr = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return arr.astype("float32")


@router.post("/upload")
async def upload_doc(sessionId: str | None = Form(default=None), file: UploadFile = File(...)):
    log.info(
        f"[RAG UPLOAD] sessionId={sessionId}, filename={file.filename}, content_type={file.content_type}"
    )
    data = await file.read()
    log.info(f"[RAG UPLOAD] file size={len(data)} bytes")
    text, mime = sniff_and_extract(file.filename, data)
    log.info(f"[RAG UPLOAD] extracted mime={mime}, text_len={len(text)}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty/unsupported file")
    chunks = chunk_text(text, {"mime": mime})
    log.info(f"[RAG UPLOAD] chunk_count={len(chunks)}")
    metas = build_metas(sessionId, file.filename, chunks, size=len(data))
    embeds = _embed([c.text for c in chunks])
    log.info(f"[RAG UPLOAD] embed_shape={embeds.shape}")
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
    out: list[SearchHit] = []
    for r in fused:
        out.append(
            SearchHit(
                id=r["id"],
                text=r["text"],
                score=float(r["score"]),
                source=r.get("source"),
                title=r.get("title"),
                sessionId=r.get("sessionId"),
            )
        )
    return {"hits": [h.model_dump() for h in out]}


@router.get("/list")
async def list_items(sessionId: str | None = None, k: int = 20):
    qv = _embed(["list"])[0]
    hits = search_vectors(sessionId, qv, topk=k, dim=qv.shape[0])
    items = []
    for h in hits:
        txt = h.get("text") or ""
        items.append(
            {
                "id": h.get("id"),
                "sessionId": h.get("sessionId"),
                "source": h.get("source"),
                "title": h.get("title"),
                "score": float(h.get("score", 0.0)),
                "text": txt,
            }
        )
    log.info(f"[RAG LIST] sessionId={sessionId} k={k} -> {len(items)} items")
    return {"items": items}


@router.get("/dump")
async def dump_items(sessionId: str | None = None, k: int = 50):
    qv = _embed(["dump"])[0]
    hits = search_vectors(sessionId, qv, topk=k, dim=qv.shape[0])
    chunks = []
    for h in hits:
        chunks.append(
            {
                "id": h.get("id"),
                "sessionId": h.get("sessionId"),
                "source": h.get("source"),
                "title": h.get("title"),
                "score": float(h.get("score", 0.0)),
                "text": h.get("text") or "",
            }
        )
    log.info(f"[RAG DUMP] sessionId={sessionId} k={k} -> {len(chunks)} items")
    return {"chunks": chunks}


@router.get("/uploads")
async def api_list_uploads(sessionId: str | None = None, scope: str = "all"):
    include_global = scope != "session"
    return {"uploads": rag_list_sources(sessionId, include_global=include_global)}


@router.post("/uploads/delete-hard")
async def api_delete_upload_hard(body: dict[str, str]):
    source = (body.get("source") or "").strip()
    session_id = body.get("sessionId") or None
    if not source:
        return {"error": "source required"}
    out = hard_delete_source(source, session_id=session_id, embedder=_embed)
    return out
