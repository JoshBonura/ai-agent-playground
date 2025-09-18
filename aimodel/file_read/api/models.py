from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx

from ..adaptive.config.paths import read_settings, write_settings
from ..runtime.model_runtime import current_model_info, list_local_models
from ..api.model_workers import supervisor, get_active_worker_addr

router = APIRouter(prefix="/api", tags=["models"])

# Convenience schema mirroring LM Studio-style options and common llama.cpp kwargs.
class LlamaKwargs(BaseModel):
    # core
    n_ctx: int | None = Field(default=None, description="Context length")
    n_threads: int | None = None
    n_gpu_layers: int | None = None
    n_batch: int | None = None
    rope_freq_base: float | None = None
    rope_freq_scale: float | None = None
    # advanced / runtime feature flags (applied if your llama.cpp build supports them)
    use_mmap: bool | None = None
    use_mlock: bool | None = None
    seed: int | None = None
    flash_attn: bool | None = None
    # KV cache types (aka cache quantization types)
    type_k: str | None = None
    type_v: str | None = None
    # open-ended pass-through; UI can stuff anything extra here
    extra: dict | None = None

class LoadReq(BaseModel):
    modelPath: str
    # Accept both flat and nested; we'll fold flat fields into llama kwargs for ergonomics
    nCtx: int | None = None
    nThreads: int | None = None
    nGpuLayers: int | None = None
    nBatch: int | None = None
    ropeFreqBase: float | None = None
    ropeFreqScale: float | None = None
    useMmap: bool | None = None
    useMlock: bool | None = None
    seed: int | None = None
    flashAttention: bool | None = None
    typeK: str | None = None
    typeV: str | None = None
    llama: LlamaKwargs | None = None

def _fold_llama_kwargs(req: LoadReq) -> dict:
    # start from nested
    base = dict(req.llama.model_dump(exclude_none=True)) if req.llama else {}
    # map flat fields → llama.cpp names
    mapping = {
        "nCtx": "n_ctx",
        "nThreads": "n_threads",
        "nGpuLayers": "n_gpu_layers",
        "nBatch": "n_batch",
        "ropeFreqBase": "rope_freq_base",
        "ropeFreqScale": "rope_freq_scale",
        "useMmap": "use_mmap",
        "useMlock": "use_mlock",
        "flashAttention": "flash_attn",
        "typeK": "type_k",
        "typeV": "type_v",
        "seed": "seed",
    }
    for src, dst in mapping.items():
        v = getattr(req, src)
        if v is not None and dst not in base:
            base[dst] = v
    # merge any nested .extra last (but don’t let it overwrite explicit keys)
    if "extra" in base and isinstance(base["extra"], dict):
        for k, v in list(base["extra"].items()):
            base.setdefault(k, v)
        base.pop("extra", None)
    return base

@router.get("/models")
async def api_list_models():
    available = list_local_models()

    worker = None
    try:
        host, port = get_active_worker_addr()
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"http://{host}:{port}/api/worker/health")
            if r.status_code == 200:
                worker = r.json()
                worker["port"] = port
    except Exception:
        worker = None

    return {
        "available": available,
        "current": current_model_info(),  # main runtime is intentionally unloaded
        "worker": worker,
        "settings": read_settings(),
    }

@router.get("/models/health")
async def models_health():
    runtime = current_model_info()
    worker = None
    worker_ok = False
    try:
        host, port = get_active_worker_addr()
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"http://{host}:{port}/api/worker/health")
            if r.status_code == 200:
                worker = r.json()
                worker_ok = bool(worker.get("ok"))
    except Exception:
        worker_ok = False

    return {
        "ok": True,
        "loaded": worker_ok,           # "loaded" tracks worker readiness now
        "config": runtime.get("config"),
        "loading": runtime.get("loading"),
        "loadingPath": runtime.get("loadingPath"),
        "worker": worker,
    }

@router.post("/models/load")
async def api_load_model(req: LoadReq):
    llama_kwargs = _fold_llama_kwargs(req)
    info = await supervisor.spawn_worker(req.modelPath, llama_kwargs=llama_kwargs)
    return {
        "ok": True,
        "worker": {
            "id": info.id,
            "port": info.port,
            "path": info.model_path,
            "status": info.status,
            "kwargs": info.kwargs or {},
        },
    }

@router.post("/models/unload")
async def api_unload_model():
    # Stop the active worker, if any
    try:
        host, port = get_active_worker_addr()
    except Exception:
        return {"ok": True, "note": "no active worker"}
    # Find & stop by port
    for w in supervisor.list():
        if w.get("port") == port:
            await supervisor.stop_worker(w.get("id"))
            break
    return {"ok": True}

@router.post("/models/cancel-load")
async def api_cancel_model_load():
    # Worker spawn is separate; nothing to cancel in-process
    return {"ok": True, "note": "no in-process load to cancel"}

@router.post("/models/settings")
async def api_update_model_settings(patch: dict[str, object]):
    s = write_settings(patch)
    return s
