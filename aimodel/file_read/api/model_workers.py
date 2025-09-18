# aimodel/file_read/api/model_workers.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx
from ..workers.model_worker import supervisor
from ..core.logging import get_logger
from ..services.system_snapshot import get_system_snapshot

router = APIRouter(prefix="/api/model-workers", tags=["model-workers"])
log = get_logger(__name__)

_ACTIVE_WORKER_ID: str | None = None

class SpawnReq(BaseModel):
    modelPath: str = Field(..., description="Absolute path to the GGUF model")

def _list_workers() -> list[dict]:
    """
    Be robust to different supervisor APIs across branches.
    Normalizes to a list[dict].
    """
    # Try most likely method names first
    for name in ("list", "list_workers", "snapshot", "status", "info"):
        if hasattr(supervisor, name):
            fn = getattr(supervisor, name)
            try:
                res = fn()
            except TypeError:
                # Some variants accept a flag; try harmless truthy
                try:
                    res = fn(True)
                except Exception:
                    continue

            # Normalize common shapes
            if isinstance(res, dict):
                if "workers" in res and isinstance(res["workers"], list):
                    return res["workers"]
                if "items" in res and isinstance(res["items"], list):
                    return res["items"]
            if isinstance(res, list):
                return res
            # Last-ditch: single worker dict
            if isinstance(res, dict):
                return [res]

    # Peek at common attributes as a final fallback
    if hasattr(supervisor, "workers"):
        w = supervisor.workers
        if isinstance(w, dict):
            return list(w.values())
        if isinstance(w, list):
            return w

    return []

def _require_active_worker_id() -> str:
    if not _ACTIVE_WORKER_ID:
        raise RuntimeError("No active worker")
    return _ACTIVE_WORKER_ID

def get_active_worker_port() -> int:
    wid = _require_active_worker_id()
    port = supervisor.get_port(wid)
    if not port:
        raise RuntimeError("Active worker not found")
    return port

def get_active_worker_addr() -> tuple[str, int]:
    return "127.0.0.1", get_active_worker_port()

@router.get("")
async def list_workers():
    return {"ok": True, "workers": _list_workers(), "active": _ACTIVE_WORKER_ID}

@router.get("/active")
async def get_active():
    if not _ACTIVE_WORKER_ID:
        return {"ok": True, "active": None}
    workers = _list_workers()
    info = next((w for w in workers if w.get("id") == _ACTIVE_WORKER_ID), None)
    return {"ok": True, "active": info}

@router.get("/inspect")
async def inspect_workers():
    sys_res = await get_system_snapshot()

    try:
        workers = supervisor.list()
    except Exception:
        workers = []

    # if registry is empty but an active id exists, try to synthesize one
    synth = None
    if (not workers) and _ACTIVE_WORKER_ID:
        try:
            host, port = get_active_worker_addr()
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"http://{host}:{port}/api/worker/health")
                h = r.json()
            synth = {
                "id": _ACTIVE_WORKER_ID,
                "port": port,
                "model_path": h.get("path"),
                "status": "ready" if h.get("ok") else "unknown",
            }
        except Exception:
            pass

    return {
        "ok": True,
        "workers": workers or ([synth] if synth else []),
        "active": _ACTIVE_WORKER_ID,
        "system": sys_res,
    }

# ✅ Make sure these POST routes are present
@router.post("/spawn")
async def spawn_worker(req: SpawnReq):
    info = await supervisor.spawn_worker(req.modelPath)
    global _ACTIVE_WORKER_ID
    if _ACTIVE_WORKER_ID is None:
        _ACTIVE_WORKER_ID = info.id
    return {
        "ok": True,
        "worker": {"id": info.id, "port": info.port, "modelPath": info.model_path, "status": info.status},
        "active": _ACTIVE_WORKER_ID,
    }

@router.post("/activate/{worker_id}")
async def activate_worker(worker_id: str):
    workers = _list_workers()
    if not any(w.get("id") == worker_id for w in workers):
        raise HTTPException(status_code=404, detail="Worker not found")
    global _ACTIVE_WORKER_ID
    _ACTIVE_WORKER_ID = worker_id
    return {"ok": True, "active": _ACTIVE_WORKER_ID}

@router.post("/kill/{worker_id}")
async def kill_worker(worker_id: str):
    ok = await supervisor.stop_worker(worker_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Worker not found")
    global _ACTIVE_WORKER_ID
    if _ACTIVE_WORKER_ID == worker_id:
        _ACTIVE_WORKER_ID = None
    return {"ok": True, "killed": worker_id, "active": _ACTIVE_WORKER_ID}

@router.post("/kill-all")
async def kill_all_workers():
    n = await supervisor.stop_all()
    global _ACTIVE_WORKER_ID
    _ACTIVE_WORKER_ID = None
    return {"ok": True, "stopped": n, "active": _ACTIVE_WORKER_ID}
