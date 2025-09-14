# deps/model_deps.py
from fastapi import HTTPException
from ..runtime.model_runtime import ensure_ready

def require_model_ready():
    try:
        ensure_ready()
    except Exception as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "MODEL_NOT_LOADED", "message": str(e)}
        )
