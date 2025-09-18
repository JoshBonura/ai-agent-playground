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

router = APIRouter(
    dependencies=[Depends(require_auth), Depends(require_model_ready)]
)

@router.get("/api/aiw/health")
async def aiw_health():
    try:
        host, port = get_active_worker_addr()
    except Exception:
        return {"ok": False, "error": "no_active_worker"}

    url = f"http://{host}:{port}/api/worker/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.error("aiw_health proxy failed: %s", e)
        return {"ok": False, "error": "worker_unreachable"}


@router.post("/api/ai/generate/stream")
async def generate_stream_alias(request: Request, data: ChatBody = Body(...)):
    """
    Single public entrypoint:
      - If a worker is active, forward ChatBody to /api/worker/generate/stream and relay bytes.
      - Else, run the in-process generate_stream_flow.
    """
    host = port = None
    try:
        host, port = get_active_worker_addr()
    except Exception:
        pass

    if host and port:
        url = f"http://{host}:{port}/api/worker/generate/stream"
        raw = await request.body()

        async def _proxy():
            # Immediate kick so the browser starts processing the stream
            yield b": proxy-open\n\n"

            # Keep upstream stream open for the whole response
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    url,
                    content=raw,
                    headers={
                        "content-type": "application/json",
                        "accept": "text/event-stream",
                        "accept-encoding": "identity",
                    },
                ) as r:
                    if r.status_code >= 400:
                        # pull body to give a real message; raise to let FastAPI format it
                        detail = await r.aread()
                        msg = (detail.decode("utf-8", "ignore") or "worker error")
                        raise HTTPException(status_code=r.status_code, detail=msg)

                    async for chunk in r.aiter_bytes():
                        # Relay exactly what the worker emits (SSE frames/comments)
                        if chunk:
                            yield chunk

        return StreamingResponse(
            _proxy(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # Fallback to in-process pipeline if no worker.
    from ..services.generate_flow import generate_stream_flow
    return await generate_stream_flow(data, request)


# ---- cancel passthrough (unchanged) ----
from ..services.generate_flow import cancel_session_alias
cancel_router = APIRouter(dependencies=[Depends(require_auth)])

@cancel_router.post("/api/ai/cancel/{session_id}")
async def _cancel_session_alias(session_id: str):
    return await cancel_session_alias(session_id)
