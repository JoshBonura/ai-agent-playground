# aimodel/file_read/api/generate_router.py
from __future__ import annotations
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..api.auth_router import require_auth
from ..core.logging import get_logger
from ..core.schemas import ChatBody
from ..deps.model_deps import require_model_ready
from .model_workers import get_active_worker_addr

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_auth), Depends(require_model_ready)])

@router.get("/api/aiw/health")
async def aiw_health():
    try:
        host, port = get_active_worker_addr()
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"http://{host}:{port}/api/worker/health")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/api/ai/generate/stream")
async def generate_stream_alias(request: Request, data: ChatBody = Body(...)):
    host, port = get_active_worker_addr()  # require worker
    url = f"http://{host}:{port}/api/worker/generate/stream"
    raw = await request.body()

    async def _proxy():
        yield b": proxy-open\n\n"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", url, content=raw,
                headers={"content-type":"application/json","accept":"text/event-stream","accept-encoding":"identity"},
            ) as r:
                if r.status_code >= 400:
                    detail = await r.aread()
                    raise HTTPException(status_code=r.status_code, detail=(detail.decode("utf-8","ignore") or "worker error"))
                async for chunk in r.aiter_bytes():
                    if chunk:
                        yield chunk

    return StreamingResponse(_proxy(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Connection":"keep-alive"})
