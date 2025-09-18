# aimodel/file_read/api/cancel_router.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from ..api.auth_router import require_auth
from ..services.generate_flow import cancel_session_alias
from ..core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])

@router.post("/api/ai/cancel/{session_id}")
async def cancel_session(session_id: str):
    return await cancel_session_alias(session_id)
