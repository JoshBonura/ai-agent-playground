from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.logging import get_logger

log = get_logger(__name__)
from ..adaptive.config.paths import read_settings, write_settings
from ..runtime.model_runtime import (current_model_info, list_local_models,
                                     load_model, unload_model)

router = APIRouter()


class LoadReq(BaseModel):
    modelPath: str
    nCtx: int | None = None
    nThreads: int | None = None
    nGpuLayers: int | None = None
    nBatch: int | None = None
    ropeFreqBase: float | None = None
    ropeFreqScale: float | None = None


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
async def api_update_settings(patch: dict[str, object]):
    s = write_settings(patch)
    return s
