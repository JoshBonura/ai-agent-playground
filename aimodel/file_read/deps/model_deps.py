# aimodel/file_read/deps/model_deps.py
from fastapi import HTTPException
import httpx
from ..api.model_workers import get_active_worker_addr

def _worker_ready() -> bool:
    try:
        host, port = get_active_worker_addr()
    except Exception:
        return False
    try:
        r = httpx.get(f"http://{host}:{port}/api/worker/health", timeout=1.5)
        j = r.json()
        return r.status_code == 200 and bool(j.get("ok"))
    except Exception:
        return False

def require_model_ready():
    if _worker_ready():
        return
    raise HTTPException(
        status_code=409,
        detail={"code": "MODEL_NOT_LOADED", "message": "No active worker/model."}
    )
