# aimodel/file_read/api/proxy_generate.py
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .model_workers import get_active_worker_addr  # <-- use addr, not port
from ..api.auth_router import require_auth  # keep auth consistent

router = APIRouter(dependencies=[Depends(require_auth)])

@router.get("/api/aiw/health")
async def proxy_health():
    try:
        host, port = get_active_worker_addr()
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    url = f"http://{host}:{port}/api/worker/health"
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(url)
        return r.json()

@router.post("/api/aiw/generate")
async def proxy_generate(req: Request):
    try:
        host, port = get_active_worker_addr()
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    body = await req.json()
    url = f"http://{host}:{port}/api/worker/generate"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=body)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@router.post("/api/aiw/generate/stream")
async def proxy_generate_stream(req: Request):
    """
    Streaming shim. The worker doesn't stream; we stream the raw bytes to fit a streaming UI.
    """
    try:
      host, port = get_active_worker_addr()
    except Exception as e:
      raise HTTPException(status_code=409, detail=str(e))
    url = f"http://{host}:{port}/api/worker/generate"
    raw = await req.body()
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post(url, content=raw, headers={"content-type": "application/json"})
        if r.status_code >= 400:
            # return body as detail so caller can show a useful error
            detail = await r.aread()
            raise HTTPException(status_code=r.status_code, detail=detail)
        return StreamingResponse(
            r.aiter_raw(),
            media_type=r.headers.get("content-type", "application/json"),
        )
