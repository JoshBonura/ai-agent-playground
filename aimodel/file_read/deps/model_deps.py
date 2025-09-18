# deps/model_deps.py
from fastapi import HTTPException
from ..runtime.model_runtime import ensure_ready

# NEW: import quick worker check
import httpx
from ..api.model_workers import get_active_worker_addr  # lightweight helper

def _worker_ready() -> bool:
    try:
        host, port = get_active_worker_addr()
    except Exception:
        return False
    try:
        # fast health probe (no auth needed for internal hop)
        url = f"http://{host}:{port}/api/worker/health"
        r = httpx.get(url, timeout=1.5)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False

def require_model_ready():
    # If main runtime is ready, we're good.
    try:
        ensure_ready()
        return
    except Exception:
        pass

    # Otherwise, accept an active worker.
    if _worker_ready():
        return

    # Neither is ready → preserve your original 409 shape.
    raise HTTPException(
        status_code=409,
        detail={"code": "MODEL_NOT_LOADED", "message": "No model loaded (runtime) and no active worker."}
    )
