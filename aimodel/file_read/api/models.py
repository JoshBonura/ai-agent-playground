from __future__ import annotations
from typing import Optional, Dict
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..adaptive.config.paths import read_settings, write_settings
from ..runtime.model_runtime import (
    list_local_models, current_model_info,
    load_model, unload_model
)

router = APIRouter()

class LoadReq(BaseModel):
    modelPath: str
    nCtx: Optional[int] = None
    nThreads: Optional[int] = None
    nGpuLayers: Optional[int] = None
    nBatch: Optional[int] = None
    ropeFreqBase: Optional[float] = None
    ropeFreqScale: Optional[float] = None

@router.get("/models")
async def api_list_models():
    return {
        "available": list_local_models(),
        "current": current_model_info(),
        "settings": read_settings(),
    }

@router.post("/models/load")
async def api_load_model(req: LoadReq):
    try:
        info = load_model(req.model_dump(exclude_none=True))
        return info
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@router.post("/models/unload")
async def api_unload_model():
    unload_model()
    return {"ok": True, "current": current_model_info()}

@router.post("/settings")
async def api_update_settings(patch: Dict[str, object]):
    s = write_settings(patch)
    return s
