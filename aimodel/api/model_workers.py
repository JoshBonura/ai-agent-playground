from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import httpx
import asyncio
import time

from ..workers.supervisor import supervisor
from ..core.logging import get_logger
from ..services.system_snapshot import get_system_snapshot

router = APIRouter(prefix="/api/model-workers", tags=["model-workers"])
log = get_logger(__name__)

# Tracks current "active" worker id (if any)
_ACTIVE_WORKER_ID: str | None = None


# -----------------------
# Request models
# -----------------------

class SpawnReq(BaseModel):
    modelPath: str = Field(..., description="Absolute path to the GGUF model")
    llamaKwargs: dict | None = Field(default=None, description="Extra kwargs for llama.cpp")

class KillByPathReq(BaseModel):
    modelPath: str = Field(..., description="Absolute path to the GGUF model")
    includeReady: bool = Field(default=True, description="Whether to also kill ready workers")
    waitMs: int = Field(default=2000, description="How long to wait for a loading worker to appear")


# -----------------------
# Helpers
# -----------------------

def _list_workers() -> list[dict]:
    """
    Try to adapt to whichever list/snapshot method the supervisor exposes.
    Returns a list of worker dicts (public shape).
    """
    for name in ("list", "list_workers", "snapshot", "status", "info"):
        if hasattr(supervisor, name):
            fn = getattr(supervisor, name)
            try:
                res = fn()
            except TypeError:
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
                # Single dict -> wrap
                return [res]
            if isinstance(res, list):
                return res

    # As a last resort, try to dig out an attribute
    if hasattr(supervisor, "workers"):
        w = supervisor.workers
        if isinstance(w, dict):
            # Might be id -> WorkerInfo; try to_public_dict if present
            out = []
            for v in w.values():
                if hasattr(v, "to_public_dict"):
                    out.append(v.to_public_dict())
                else:
                    out.append(v)
            return out
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


# -----------------------
# Routes
# -----------------------

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
                "kwargs": h.get("kwargs") or {},
            }
        except Exception:
            pass

    return {
        "ok": True,
        "workers": workers or ([synth] if synth else []),
        "active": _ACTIVE_WORKER_ID,
        "system": sys_res,
    }


@router.post("/spawn")
async def spawn_worker(req: SpawnReq, request: Request):
    global _ACTIVE_WORKER_ID
    t0 = time.perf_counter()
    tid = request.headers.get("X-Trace-Id") or "no-trace"
    try:
        log.info("[api.spawn] trace=%s req.modelPath=%s llamaKwargs=%s", tid, req.modelPath, (req.llamaKwargs or {}))
        info = await supervisor.spawn_worker(req.modelPath, llama_kwargs=req.llamaKwargs or {})
        cur = supervisor.get_worker(info.id) or info
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info("[api.spawn] trace=%s created id=%s path=%s status=%s dt=%.1fms kwargs=%s",
                 tid, cur.id, cur.model_path, cur.status, dt_ms, (cur.kwargs or {}))

        if _ACTIVE_WORKER_ID is None:
            _ACTIVE_WORKER_ID = cur.id

        return {
            "ok": True,
            "worker": {
                "id": cur.id,
                "port": cur.port,
                "modelPath": cur.model_path,
                "status": cur.status,
                "kwargs": cur.kwargs or {},
            },
            "active": _ACTIVE_WORKER_ID,
        }
    except RuntimeError as e:
        diag = getattr(supervisor, "_last_guardrail_diag", {}) or {}
        log.warning("[api.spawn] trace=%s guardrail_abort diag=%s", tid, diag)
        raise HTTPException(
            status_code=409,
            detail={"error": "guardrail_abort", "message": str(e), **diag}
        )




@router.post("/activate/{worker_id}")
async def activate_worker(worker_id: str):
    global _ACTIVE_WORKER_ID  # assigning later

    workers = _list_workers()
    if not any(w.get("id") == worker_id for w in workers):
        raise HTTPException(status_code=404, detail="Worker not found")

    _ACTIVE_WORKER_ID = worker_id
    log.info("[api.activate] active set to %s", _ACTIVE_WORKER_ID)
    return {"ok": True, "active": _ACTIVE_WORKER_ID}


@router.post("/kill/{worker_id}")
async def kill_worker(worker_id: str):
    global _ACTIVE_WORKER_ID  # assigning later

    # Log the incoming request and currently known ids
    try:
        workers = supervisor.list()
    except Exception:
        workers = []
    ids = [w.get("id") for w in workers]
    log.info("[api.kill] incoming worker_id=%s known=%s", worker_id, ids)

    ok = await supervisor.stop_worker(worker_id)
    log.info("[api.kill] stop_worker called id=%s ok=%s", worker_id, ok)

    if not ok:
        log.warning("[api.kill] 404: worker not found id=%s", worker_id)
        raise HTTPException(status_code=404, detail="Worker not found")

    if _ACTIVE_WORKER_ID == worker_id:
        log.info("[api.kill] clearing _ACTIVE_WORKER_ID=%s", _ACTIVE_WORKER_ID)
        _ACTIVE_WORKER_ID = None

    log.info("[api.kill] success killed=%s active=%s", worker_id, _ACTIVE_WORKER_ID)
    return {"ok": True, "killed": worker_id, "active": _ACTIVE_WORKER_ID}


@router.post("/kill-all")
async def kill_all_workers():
    global _ACTIVE_WORKER_ID  # assigning later

    t0 = time.perf_counter()
    n = await supervisor.stop_all()
    _ACTIVE_WORKER_ID = None
    dt_ms = (time.perf_counter() - t0) * 1000.0
    log.info("[api.kill_all] stopped=%s dt=%.1fms", n, dt_ms)
    return {"ok": True, "stopped": n, "active": _ACTIVE_WORKER_ID}


@router.post("/kill-by-path")
async def kill_by_path(req: KillByPathReq):
    t0 = time.perf_counter()
    log.info("[api.kill_by_path] incoming modelPath=%s includeReady=%s waitMs=%s",
             req.modelPath, req.includeReady, req.waitMs)

    # Fast path: if already queued, short-circuit
    if req.modelPath in supervisor._kill_on_spawn_paths:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info("[api.kill_by_path] already queued path=%s dt=%.1fms", req.modelPath, dt_ms)
        return {"ok": True, "killed": [], "queued": True, "note": "already-queued"}

    initial = await supervisor.request_kill_by_path(
        req.modelPath, include_ready=req.includeReady
    )
    log.info("[api.kill_by_path] initial result=%s", initial)

    if initial and initial.get("killed"):
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info("[api.kill_by_path] killed immediately modelPath=%s killed=%s dt=%.1fms",
                 req.modelPath, initial["killed"], dt_ms)
        return {"ok": True, **initial, "note": "killed existing"}

    if not initial or not initial.get("queued"):
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info("[api.kill_by_path] no match, nothing queued modelPath=%s dt=%.1fms",
                 req.modelPath, dt_ms)
        return {"ok": True, **(initial or {"killed": [], "queued": False}), "note": "no matching worker"}

    deadline = time.time() + max(0, req.waitMs) / 1000.0
    killed_now: list[str] = []

    while time.time() < deadline:
        matches = supervisor._find_workers_by_path(req.modelPath)
        log.debug("[api.kill_by_path] polling matches=%s", [m.id for m in matches])
        if matches:
            for info in matches:
                if (not req.includeReady) and info.status != "loading":
                    continue
                ok = await supervisor._kill_worker_info(info)
                log.info("[api.kill_by_path] tried killing id=%s ok=%s", info.id, ok)
                if ok:
                    killed_now.append(info.id)
            supervisor._kill_on_spawn_paths.discard(req.modelPath)
            break
        await asyncio.sleep(0.05)

    dt_ms = (time.perf_counter() - t0) * 1000.0
    queued_flag = (req.modelPath in supervisor._kill_on_spawn_paths)
    log.info("[api.kill_by_path] final killed=%s queued=%s dt=%.1fms",
             killed_now, queued_flag, dt_ms)

    return {
        "ok": True,
        "killed": killed_now,
        "queued": queued_flag,
        "sinceQueuedMs": dt_ms if queued_flag and not killed_now else 0.0,
        "note": ("killed-after-wait" if killed_now else ("queued-will-kill-on-spawn" if queued_flag else "no-op")),
    }

