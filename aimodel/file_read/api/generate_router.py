from fastapi import APIRouter, Body, Request
from ..core.schemas import ChatBody
from ..services.generate_flow import generate_stream_flow, cancel_session_alias

router = APIRouter()

@router.post("/api/ai/generate/stream")
async def generate_stream_alias(request: Request, data: ChatBody = Body(...)):
    return await generate_stream_flow(data, request)

@router.post("/api/ai/cancel/{session_id}")
async def _cancel_session_alias(session_id: str):
    return await cancel_session_alias(session_id)
