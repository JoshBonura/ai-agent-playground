from __future__ import annotations

from ..core.logging import get_logger
log = get_logger(__name__)

from threading import RLock
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends, Request
from sentence_transformers import SentenceTransformer

from ..deps.license_deps import require_personal_pro_activated
from ..rag.ingest import build_metas, chunk_text, sniff_and_extract
from ..rag.schemas import SearchHit, SearchReq
from ..rag.store import add_vectors, search_vectors
from ..rag.uploads import hard_delete_source
from ..rag.uploads import list_sources as rag_list_sources

router = APIRouter(
    prefix="/api/rag",
    tags=["rag"],
    dependencies=[Depends(require_personal_pro_activated)],  # Pro + Activation, no admin
)

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


# --------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------
@router.post("/upload")
async def upload_doc(
    request: Request,
    sessionId: str | None = Form(default=None),
    file: UploadFile = File(...),
):
    # Entry log (helps prove the request actually reached this handler)
    log.info(
        "[RAG UPLOAD] entered handler method=%s path=%s ct=%s",
        request.method,
        request.url.path,
        request.headers.get("content-type"),
    )

    log.info(
        "[RAG UPLOAD] sessionId=%s, filename=%s, content_type=%s",
        sessionId,
        getattr(file, "filename", None),
        getattr(file, "content_type", None),
    )
    data = await file.read()
    log.info("[RAG UPLOAD] file size=%d bytes", len(data))
    text, mime = sniff_and_extract(file.filename, data)
    log.info("[RAG UPLOAD] extracted mime=%s, text_len=%d", mime, len(text))
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty/unsupported file")
    chunks = chunk_text(text, {"mime": mime})
    log.info("[RAG UPLOAD] chunk_count=%d", len(chunks))
    metas = build_metas(sessionId, file.filename, chunks, size=len(data))
    embeds = _embed([c.text for c in chunks])
    log.info("[RAG UPLOAD] embed_shape=%s", getattr(embeds, "shape", None))
    add_vectors(sessionId, embeds, metas, dim=embeds.shape[1])
    log.info("[RAG UPLOAD] done added=%d", len(chunks))
    return {"ok": True, "added": len(chunks)}


# Optional: respond to OPTIONS explicitly (useful if CORS preflight is involved)
@router.options("/upload")
async def options_upload():
    return {}


# --------------------------------------------------------------------
# Search
# --------------------------------------------------------------------
@router.post("/search")
async def search(req: SearchReq, request: Request):
    log.info(
        "[RAG SEARCH] entered handler method=%s path=%s",
        request.method,
        request.url.path,
    )
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


# --------------------------------------------------------------------
# List / Dump
# --------------------------------------------------------------------
@router.get("/list")
async def list_items(sessionId: str | None = None, k: int = 20, request: Request = None):
    if request is not None:
        log.info(
            "[RAG LIST] entered handler method=%s path=%s sessionId=%s k=%d",
            request.method,
            request.url.path,
            sessionId,
            k,
        )
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
    log.info("[RAG LIST] sessionId=%s k=%d -> %d items", sessionId, k, len(items))
    return {"items": items}


@router.get("/dump")
async def dump_items(sessionId: str | None = None, k: int = 50, request: Request = None):
    if request is not None:
        log.info(
            "[RAG DUMP] entered handler method=%s path=%s sessionId=%s k=%d",
            request.method,
            request.url.path,
            sessionId,
            k,
        )
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
    log.info("[RAG DUMP] sessionId=%s k=%d -> %d items", sessionId, k, len(chunks))
    return {"chunks": chunks}


# --------------------------------------------------------------------
# Uploads index / delete
# --------------------------------------------------------------------
@router.get("/uploads")
async def api_list_uploads(sessionId: str | None = None, scope: str = "all", request: Request = None):
    if request is not None:
        log.info(
            "[RAG UPLOADS LIST] entered handler method=%s path=%s sessionId=%s scope=%s",
            request.method,
            request.url.path,
            sessionId,
            scope,
        )
    include_global = scope != "session"
    return {"uploads": rag_list_sources(sessionId, include_global=include_global)}


@router.options("/uploads")
async def options_uploads():
    return {}


@router.post("/uploads/delete-hard")
async def api_delete_upload_hard(body: dict[str, str], request: Request):
    log.info(
        "[RAG UPLOADS DELETE] entered handler method=%s path=%s",
        request.method,
        request.url.path,
    )
    source = (body.get("source") or "").strip()
    session_id = body.get("sessionId") or None
    if not source:
        return {"error": "source required"}
    out = hard_delete_source(source, session_id=session_id, embedder=_embed)
    return out


# --------------------------------------------------------------------
# Debug: list the routes this router actually registered
# --------------------------------------------------------------------
try:
    for r in router.routes:
        methods = sorted(list(getattr(r, "methods", []) or []))
        path = getattr(r, "path", "")
        log.info("[RAG ROUTER] registered %s %s", methods, path)
except Exception as e:
    log.error("[RAG ROUTER] failed to list router routes: %r", e)
