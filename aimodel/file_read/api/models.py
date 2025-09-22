from __future__ import annotations
from ..core.logging import get_logger
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
import httpx, time
from fastapi.responses import JSONResponse, Response
from ..store.paths import read_settings, write_settings
from ..runtime.model_runtime import current_model_info, list_models_cached, _CACHE, _CACHE_TTL
from ..api.model_workers import supervisor, get_active_worker_addr

router = APIRouter(prefix="/api", tags=["models"])
log = get_logger(__name__)

class LlamaKwargs(BaseModel):
    n_ctx: int | None = Field(default=None, description="Context length")
    n_threads: int | None = None
    n_gpu_layers: int | None = None
    n_batch: int | None = None
    rope_freq_base: float | None = None
    rope_freq_scale: float | None = None
    use_mmap: bool | None = None
    use_mlock: bool | None = None
    seed: int | None = None
    flash_attn: bool | None = None
    type_k: str | None = None
    type_v: str | None = None
    extra: dict | None = None

class LoadReq(BaseModel):
    modelPath: str
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
    base = dict(req.llama.model_dump(exclude_none=True)) if req.llama else {}
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
    if isinstance(base.get("extra"), dict):
        for k, v in list(base["extra"].items()):
            base.setdefault(k, v)
        base.pop("extra", None)
    if str(base.get("n_gpu_layers", "")).strip() in {"0", "0.0"}:
        base.pop("n_gpu_layers", None)
    return base

@router.get("/models")
async def api_list_models(request: Request, fast: bool = True):
    inm = request.headers.get("if-none-match")
    headers = {"Cache-Control": "no-cache"}
    now = time.time()
    if inm and _CACHE.get("etag") and (now - (_CACHE.get("ts") or 0) < _CACHE_TTL) and inm == _CACHE["etag"]:
        return Response(status_code=304, headers={**headers, "ETag": _CACHE["etag"]})
    models, etag = list_models_cached(with_ctx=not fast)
    headers["ETag"] = etag
    if inm and inm == etag:
        return Response(status_code=304, headers=headers)
    worker = None
    try:
        host, port = get_active_worker_addr()
        async with httpx.AsyncClient(timeout=0.25) as client:
            r = await client.get(f"http://{host}:{port}/api/worker/health")
            if r.status_code == 200:
                worker = r.json()
                worker["port"] = port
    except Exception:
        worker = None
    payload = {
        "available": models,
        "current": current_model_info(),
        "worker": worker,
        "settings": read_settings(),
    }
    return JSONResponse(payload, headers=headers)

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
        "loaded": worker_ok,
        "config": runtime.get("config"),
        "loading": runtime.get("loading"),
        "loadingPath": runtime.get("loadingPath"),
        "worker": worker,
        "kv_offload": (worker or {}).get("kwargs", {}).get("kv_offload"),
    }

@router.post("/models/load")
async def api_load_model(req: LoadReq):
    try:
        flat_fields = {
            k: getattr(req, k)
            for k in [
                "nCtx",
                "nThreads",
                "nGpuLayers",
                "nBatch",
                "ropeFreqBase",
                "ropeFreqScale",
                "useMmap",
                "useMlock",
                "seed",
                "flashAttention",
                "typeK",
                "typeV",
            ]
            if getattr(req, k) is not None
        }
        nested = req.llama.model_dump(exclude_none=True) if req.llama else {}
        log.info(
            "[models.load] incoming req: model=%r flat=%s nested=%s",
            req.modelPath,
            flat_fields,
            {k: v for k, v in nested.items() if k != "extra"},
        )
    except Exception as e:
        log.warning("[models.load] provenance log failed: %r", e)
    llama_kwargs = _fold_llama_kwargs(req)
    log.info("[models.load] folded llama kwargs: %s", llama_kwargs)
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
    try:
        host, port = get_active_worker_addr()
    except Exception:
        return {"ok": True, "note": "no active worker"}
    for w in supervisor.list():
        if w.get("port") == port:
            await supervisor.stop_worker(w.get("id"))
            break
    return {"ok": True}

@router.post("/models/cancel-load")
async def api_cancel_model_load():
    return {"ok": True, "note": "no in-process load to cancel"}

@router.post("/models/settings")
async def api_update_model_settings(patch: dict[str, object]):
    s = write_settings(patch)
    return s
