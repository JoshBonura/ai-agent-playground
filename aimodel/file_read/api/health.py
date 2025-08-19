from __future__ import annotations
from fastapi import APIRouter
from ..model_runtime import current_model_info

router = APIRouter()

@router.get("/health")
async def health():
    try:
        info = current_model_info()
        return {"ok": True, "model": info}
    except Exception as e:
        return {"ok": True, "model": {"loaded": False, "error": str(e)}}
