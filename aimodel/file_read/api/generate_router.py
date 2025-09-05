# aimodel/file_read/api/generate_router.py
from __future__ import annotations
from fastapi import APIRouter, Body, Request
from ..core.schemas import ChatBody
from ..services.generate_flow import generate_stream_flow, cancel_session, cancel_session_alias
from ..services.cancel import is_active 

router = APIRouter()


# legacy alias (kept identical)
@router.post("/api/ai/generate/stream")
async def generate_stream_alias(data: ChatBody = Body(...), request: Request = None):
    return await generate_stream_flow(data, request)

@router.post("/api/ai/cancel/{session_id}")
async def _cancel_session_alias(session_id: str):
    return await cancel_session_alias(session_id)
