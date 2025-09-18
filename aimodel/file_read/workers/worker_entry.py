from __future__ import annotations

# Initialize logging ASAP
from aimodel.file_read.core.logging import setup_logging, get_logger
setup_logging()
wlog = get_logger("aimodel.worker")
wlog.info("worker logging initialized")

import gc
import inspect
import json
import os
import signal
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import StreamingResponse

try:
    from llama_cpp import Llama  # type: ignore
except Exception as e:
    raise RuntimeError("llama-cpp-python not installed in worker") from e

from aimodel.file_read.core.schemas import ChatBody
from aimodel.file_read.services.generate_flow import generate_stream_flow, cancel_session as _cancel

def _env_num(name: str, typ, default=None):
    v = os.getenv(name, "")
    if not v:
        return default
    try:
        return typ(v)
    except Exception:
        return default

@dataclass
class WorkerCfg:
    model_path: str
    n_ctx: int = 4096
    n_threads: int = _env_num("N_THREADS", int, 8) or 8
    n_gpu_layers: int = _env_num("N_GPU_LAYERS", int, 40) or 40
    n_batch: int = _env_num("N_BATCH", int, 256) or 256
    rope_freq_base: Optional[float] = _env_num("ROPE_FREQ_BASE", float, None)
    rope_freq_scale: Optional[float] = _env_num("ROPE_FREQ_SCALE", float, None)

    @staticmethod
    def from_env() -> "WorkerCfg":
        mp = (os.getenv("MODEL_PATH") or "").strip()
        if not mp:
            raise RuntimeError("MODEL_PATH env is required for worker")
        return WorkerCfg(
            model_path=mp,
            n_ctx=_env_num("N_CTX", int, 4096) or 4096,
        )

app = FastAPI(title="LocalMind Model Worker", version="0.2")

_llm: Optional[Llama] = None
_cfg: Optional[WorkerCfg] = None
_applied_kwargs: Dict[str, Any] = {}

def _build_kwargs(cfg: WorkerCfg) -> Dict[str, Any]:
    kw: Dict[str, Any] = dict(
        model_path=cfg.model_path,
        n_ctx=cfg.n_ctx,
        n_threads=cfg.n_threads,
        n_gpu_layers=cfg.n_gpu_layers,
        n_batch=cfg.n_batch,
    )
    if cfg.rope_freq_base is not None:
        kw["rope_freq_base"] = cfg.rope_freq_base
    if cfg.rope_freq_scale is not None:
        kw["rope_freq_scale"] = cfg.rope_freq_scale
    return kw

def _attach_introspection(llm: Llama):
    def get_last_timings():
        for attr in ("get_timings", "timings", "perf"):
            try:
                obj = getattr(llm, attr, None)
                v = obj() if callable(obj) else obj
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
        return None
    try:
        llm.get_last_timings = get_last_timings  # type: ignore[attr-defined]
    except Exception:
        pass

def _close_llm():
    global _llm
    try:
        if _llm is not None:
            try:
                del _llm
            finally:
                _llm = None
                gc.collect()
    except Exception:
        _llm = None
        gc.collect()

def _patch_main_runtime_with_worker_llm(llm: Llama):
    try:
        from aimodel.file_read.runtime import model_runtime as MR
        def _ensure_ready(): return True
        def _get_llm(): return llm
        MR.ensure_ready = _ensure_ready          # type: ignore[attr-defined]
        MR.get_llm = _get_llm                    # type: ignore[attr-defined]
        try:
            setattr(MR, "_LLM", llm)
        except Exception:
            pass
        wlog.info("patched model_runtime to use worker LLM")
    except Exception as e:
        wlog.warning(f"failed to patch model_runtime: {e}")

def _parse_llama_kwargs_from_env() -> Dict[str, Any]:
    raw = os.getenv("LLAMA_KWARGS_JSON") or ""
    if not raw.strip():
        return {}
    try:
        d = json.loads(raw)
        if not isinstance(d, dict):
            return {}
        return d
    except Exception:
        return {}

def _filter_llama_kwargs(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Only keep kwargs actually accepted by Llama.__init__ to avoid TypeError."""
    try:
        sig = inspect.signature(Llama.__init__)
        allowed = set(sig.parameters.keys()) - {"self"}
    except Exception:
        # fallback to a conservative list
        allowed = {
            "model_path", "n_ctx", "n_threads", "n_gpu_layers", "n_batch",
            "rope_freq_base", "rope_freq_scale", "seed",
            "use_mmap", "use_mlock",
            "flash_attn",
            "type_k", "type_v",
        }
    out: Dict[str, Any] = {}
    for k, v in (extra or {}).items():
        if k in allowed:
            out[k] = v
    return out

@app.get("/api/worker/log-test")
def _log_test():
    lg = get_logger("aimodel.worker.logtest")
    lg.debug("debug: hello from worker")
    lg.info("info: hello from worker")
    lg.warning("warn: hello from worker")
    return {"ok": True}

@app.on_event("startup")
def _startup():
    global _llm, _cfg, _applied_kwargs
    _cfg = WorkerCfg.from_env()
    base_kw = _build_kwargs(_cfg)

    # merge extra kwargs (from /api/models/load payload)
    extra = _parse_llama_kwargs_from_env()
    extra = _filter_llama_kwargs(extra)
    for k, v in extra.items():
        # don't let extra clobber model_path
        if k == "model_path":
            continue
        base_kw[k] = v
    _applied_kwargs = dict(base_kw)
    wlog.info(f"startup cwd={os.getcwd()} py={sys.version.split()[0]}")
    wlog.info(f"MODEL_PATH={_cfg.model_path}")
    wlog.info(f"llama kwargs: {json.dumps(_redact(base_kw), ensure_ascii=False)}")

    _llm = Llama(**base_kw)
    _attach_introspection(_llm)
    _patch_main_runtime_with_worker_llm(_llm)
    wlog.info("llama initialized OK")

    try:
        from aimodel.file_read.core.settings import SETTINGS as _S
        from aimodel.file_read.deps.license_deps import is_request_pro_activated as _pro
        wlog.info(
            f"worker settings: runjson_emit={bool(_S.runjson_emit)} "
            f"stream_emit_stopped_line={bool(_S.stream_emit_stopped_line)}"
        )
        wlog.info(f"worker license: pro={bool(_pro())}")
    except Exception as e:
        wlog.info(f"worker settings/license probe failed: {e}")

def _redact(kw: Dict[str, Any]) -> Dict[str, Any]:
    # nothing sensitive here normally; keep hook for future
    return kw

@app.get("/api/worker/health")
def worker_health():
    if _cfg is None:
        return {"ok": False}
    name = os.path.basename(_cfg.model_path)
    return {
        "ok": _llm is not None,
        "model": name,
        "path": _cfg.model_path,
        "kwargs": _applied_kwargs,  # ← echo all kwargs actually used
    }

@app.get("/api/worker/diag")
def worker_diag():
    return {
        "cwd": os.getcwd(),
        "python": sys.version,
        "env": {
            "MODEL_PATH": os.getenv("MODEL_PATH"),
            "N_CTX": os.getenv("N_CTX"),
            "N_THREADS": os.getenv("N_THREADS"),
            "N_GPU_LAYERS": os.getenv("N_GPU_LAYERS"),
            "N_BATCH": os.getenv("N_BATCH"),
        },
        "llm_ready": _llm is not None,
        "kwargs": _applied_kwargs,
    }

@app.on_event("shutdown")
def _shutdown():
    _close_llm()

def _sigterm(_signum, _frame):
    try:
        _close_llm()
    finally:
        os._exit(0)
signal.signal(signal.SIGTERM, _sigterm)

@app.post("/api/worker/generate/stream")
async def worker_generate_stream(request: Request, data: ChatBody = Body(...)) -> StreamingResponse:
    if _llm is None:
        raise HTTPException(status_code=503, detail="Model not ready")
    return await generate_stream_flow(data, request)

@app.post("/api/worker/cancel/{session_id}")
async def worker_cancel(session_id: str):
    return await _cancel(session_id)

@app.post("/api/worker/shutdown")
def worker_shutdown():
    try:
        _close_llm()
    finally:
        os._exit(0)
