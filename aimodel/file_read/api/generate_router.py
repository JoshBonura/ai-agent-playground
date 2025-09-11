from fastapi import APIRouter, Body, Request

from ..core.logging import get_logger
from ..core.schemas import ChatBody
from ..services.generate_flow import cancel_session_alias, generate_stream_flow

log = get_logger(__name__)

router = APIRouter()


@router.post("/api/ai/generate/stream")
async def generate_stream_alias(request: Request, data: ChatBody = Body(...)):
    return await generate_stream_flow(data, request)


@router.post("/api/ai/cancel/{session_id}")
async def _cancel_session_alias(session_id: str):
    return await cancel_session_alias(session_id)
