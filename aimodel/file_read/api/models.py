# aimodel/file_read/api/models.py
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..adaptive.config.paths import read_settings, write_settings
from ..runtime.model_runtime import (
    current_model_info,
    list_local_models,
    load_model,
    unload_model,
)

router = APIRouter(prefix="/api", tags=["models"])

class LoadReq(BaseModel):
    modelPath: str
    nCtx: int | None = None
    nThreads: int | None = None
    nGpuLayers: int | None = None
    nBatch: int | None = None
    ropeFreqBase: float | None = None
    ropeFreqScale: float | None = None
    resetDefaults: bool | None = None   # ← NEW

@router.get("/models")
async def api_list_models():
    return {
        "available": list_local_models(),
        "current": current_model_info(),
        "settings": read_settings(),
    }

@router.get("/models/health")
def models_health():
    info = current_model_info()
    return {"ok": True, "loaded": info["loaded"], "config": info["config"]}

@router.post("/models/load")
async def api_load_model(req: LoadReq):
    try:
        payload = req.model_dump(exclude_none=True)
        # IMPORTANT: pass as a single dict (no ** expansion)
        info = load_model(payload)
        return info
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@router.post("/models/unload")
async def api_unload_model():
    unload_model()
    return {"ok": True, "current": current_model_info()}

@router.post("/models/settings")
async def api_update_model_settings(patch: dict[str, object]):
    s = write_settings(patch)
    return s
