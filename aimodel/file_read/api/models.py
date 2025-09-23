from __future__ import annotations
from ..core.logging import get_logger
from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, Field
import httpx, time
from fastapi.responses import JSONResponse, Response
from ..store.paths import read_settings, write_settings
from ..runtime.model_runtime import current_model_info, list_models_cached, _CACHE, _CACHE_TTL
from ..api.model_workers import supervisor, get_active_worker_addr
from ..services.system_snapshot import get_system_snapshot
from ..runtime.model_runtime import read_model_meta_from_gguf
from ..services.accel_prefs import read_pref, detect_backends
from typing import Optional
from pathlib import Path
import gguf

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

def _read_gguf_header_min(path: str) -> dict[str, Optional[int | str]]:
    out = {"n_ctx_train": None, "n_layer": None, "arch": None}
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".gguf":
        log.info("[gguf] skip: not gguf: %r", path)
        return out

    try:
        import gguf
        r = gguf.GGUFReader(str(p))

        has_helpers = hasattr(r, "get_field") and hasattr(gguf, "gguf_scalar_to_np")

        def _coerce_scalar(field):
            v = gguf.gguf_scalar_to_np(field)
            if hasattr(v, "item"):  # numpy scalar -> python
                v = v.item()
            if isinstance(v, (bytes, bytearray, memoryview)):
                try: v = bytes(v).decode("utf-8", "ignore")
                except Exception: v = None
            return v

        def get_int(*keys):
            if not has_helpers:
                return None
            for k in keys:
                try:
                    f = r.get_field(k)
                    if f is None: 
                        continue
                    v = _coerce_scalar(f)
                    return int(v)
                except Exception:
                    continue
            return None

        def get_str(*keys):
            if not has_helpers:
                return None
            for k in keys:
                try:
                    f = r.get_field(k)
                    if f is None:
                        continue
                    v = _coerce_scalar(f)
                    if isinstance(v, str) and v:
                        return v
                except Exception:
                    continue
            return None

        # try direct KV first
        out["n_ctx_train"] = get_int(
            "llama.context_length", "general.context_length", "context_length"
        )
        out["n_layer"] = get_int(
            "llama.block_count", "llama.num_layers", "general.block_count",
            "block_count", "n_layer"
        )
        out["arch"] = get_str(
            "general.architecture", "llama.architecture", "architecture"
        )

        # fallback: derive layer count from tensors if missing
        if out["n_layer"] is None:
            try:
                # count blocks by presence of attention.k.weight tensors
                tensor_names = [t.name if hasattr(t, "name") else getattr(t, 0, None) for t in r.tensors]
                blocks = {name.split(".")[1] for name in tensor_names
                          if isinstance(name, str) and name.startswith("blk.") and ".attn_k" in name}
                if blocks:
                    out["n_layer"] = len(blocks)
                    log.info("[gguf] layers derived via tensors: %s", out["n_layer"])
            except Exception:
                pass

        log.info("[gguf] header-min result ctx=%s layers=%s arch=%s",
                 out["n_ctx_train"], out["n_layer"], out["arch"])

    except Exception as e:
        log.warning("[gguf] header parse failed: %s", e)

    return out





@router.get("/models/capabilities")
async def models_capabilities(request: Request, modelPath: str | None = Query(default=None)):
    xid = f"cap_{int(time.time()*1000)%100000}"  # or your trace id helper
    log.info("[cap] %s begin", xid)

    # 1) System snapshot (always available)
    sysr = await get_system_snapshot()
    cpu_threads = (sysr.get("cpu") or {}).get("countLogical") or None
    accel_pref = read_pref().accel  # "auto"|"cpu"|"cuda"|"metal"|"rocm"
    accel_detected = ("cuda" if (sysr.get("caps") or {}).get("cuda") else
                      "metal" if (sysr.get("caps") or {}).get("metal") else
                      "rocm" if (sysr.get("caps") or {}).get("hip") else
                      "cpu")
    # prefer explicit pref if not "auto"
    accel = accel_pref if accel_pref != "auto" else accel_detected

    header_ctx = None
    n_layers_hdr = None
    arch_hdr = None

    # 2) Optional: read model header if modelPath provided
    if modelPath:
        hdr = _read_gguf_header_min(modelPath)
        header_ctx = hdr.get("n_ctx_train")
        n_layers_hdr = hdr.get("n_layer")
        arch_hdr = hdr.get("arch")
        # 🔎 new diagnostics
        log.info("[cap] hdr path=%s ctx=%s layers=%s arch=%s",
                 modelPath, header_ctx, n_layers_hdr, arch_hdr)

    # 3) Active worker health (may be absent)
    eff_ctx = None
    offload_layers = None
    kv_off = None
    try:
        host, port = get_active_worker_addr()
        async with httpx.AsyncClient(timeout=0.5) as client:
            r = await client.get(f"http://{host}:{port}/api/worker/health")
            if r.status_code == 200:
                h = r.json()
                eff_ctx = h.get("n_ctx")
                offload_layers = h.get("n_gpu_layers")
                kv_off = (h.get("kwargs") or {}).get("kv_offload")
    except Exception as e:
        log.info("[cap] %s no active worker: %r", xid, e)

    log.info("[cap] %s result eff_ctx=%s offload=%s kv=%s accel=%s path=%s",
             xid, eff_ctx, offload_layers, kv_off, accel, modelPath or None)

    return {
        "ok": True,
        "maxTokens": {"effective": eff_ctx, "header": header_ctx},
        "cpu": {"threads": cpu_threads},
        "gpu": {
            "offloadLayers": offload_layers if offload_layers is not None else n_layers_hdr,
            "kvOffload": kv_off,
            "accel": accel,
        },
        "model": {"path": modelPath, "arch": arch_hdr, "nLayersHeader": n_layers_hdr},
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
