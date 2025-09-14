from fastapi import APIRouter, Body, Request, Depends
from ..core.logging import get_logger
from ..core.schemas import ChatBody
from ..services.generate_flow import generate_stream_flow, cancel_session_alias
from ..deps.model_deps import require_model_ready
from ..api.auth_router import require_auth

log = get_logger(__name__)

router = APIRouter(
    dependencies=[Depends(require_auth), Depends(require_model_ready)]
)

@router.post("/api/ai/generate/stream")
async def generate_stream_alias(request: Request, data: ChatBody = Body(...)):
    return await generate_stream_flow(data, request)

cancel_router = APIRouter(dependencies=[Depends(require_auth)])

@cancel_router.post("/api/ai/cancel/{session_id}")
async def _cancel_session_alias(session_id: str):
    return await cancel_session_alias(session_id)
