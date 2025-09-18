# aimodel/file_read/workers/worker_entry.py
from __future__ import annotations

# ✅ INIT LOGGING FIRST so all modules that call get_logger(...) emit in this process
from aimodel.file_read.core.logging import setup_logging, get_logger
setup_logging()  # root INFO, StreamHandler with your formatter
wlog = get_logger("aimodel.worker")
wlog.info("worker logging initialized")

import os
import signal
import sys
import gc
from dataclasses import dataclass
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import StreamingResponse

try:
    from llama_cpp import Llama  # type: ignore
except Exception as e:
    raise RuntimeError("llama-cpp-python not installed in worker") from e

# ⬇️ AFTER setup_logging so generate_flow’s logger is configured
from aimodel.file_read.core.schemas import ChatBody
from aimodel.file_read.services.generate_flow import generate_stream_flow, cancel_session as _cancel


def _log(msg: str):
    print(f"[worker] {msg}", flush=True)

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

app = FastAPI(title="LocalMind Model Worker", version="0.1")

_llm: Optional[Llama] = None
_cfg: Optional[WorkerCfg] = None


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
    """
    Make the shared pipeline use THIS worker's Llama.
    """
    try:
        from aimodel.file_read.runtime import model_runtime as MR

        # Replace getters to point at the worker's LLM
        def _ensure_ready():
            # no-op; worker initializes the model at startup
            return True

        def _get_llm():
            return llm

        # Patch
        MR.ensure_ready = _ensure_ready          # type: ignore[attr-defined]
        MR.get_llm = _get_llm                    # type: ignore[attr-defined]
        # If MR keeps a private handle, set it for good measure
        try:
            setattr(MR, "_LLM", llm)
        except Exception:
            pass

        _log("patched model_runtime to use worker LLM")
    except Exception as e:
        _log(f"failed to patch model_runtime: {e}")
        
@app.get("/api/worker/log-test")
def _log_test():
    lg = get_logger("aimodel.worker.logtest")
    lg.debug("debug: hello from worker")
    lg.info("info: hello from worker")
    lg.warning("warn: hello from worker")
    return {"ok": True}

@app.on_event("startup")
def _startup():
    global _llm, _cfg
    _cfg = WorkerCfg.from_env()
    kw = _build_kwargs(_cfg)
    _log(f"startup cwd={os.getcwd()} py={sys.version.split()[0]}")
    _log(f"MODEL_PATH={_cfg.model_path}")
    _log(f"kwargs={kw}")
    _llm = Llama(**kw)
    _attach_introspection(_llm)
    _patch_main_runtime_with_worker_llm(_llm)
    _log("llama initialized OK")

    

    try:
        from aimodel.file_read.core.settings import SETTINGS as _S
        from aimodel.file_read.deps.license_deps import is_request_pro_activated as _pro
        _log(f"worker settings: runjson_emit={bool(_S.runjson_emit)} "
             f"stream_emit_stopped_line={bool(_S.stream_emit_stopped_line)}")
        _log(f"worker license: pro={bool(_pro())}")
    except Exception as e:
        _log(f"worker settings/license probe failed: {e}")

@app.get("/api/worker/health")
def worker_health():
    if _cfg is None:
        return {"ok": False}
    name = os.path.basename(_cfg.model_path)
    return {
        "ok": _llm is not None,
        "model": name,
        "path": _cfg.model_path,
        "n_ctx": _cfg.n_ctx,
        "n_threads": _cfg.n_threads,
        "n_gpu_layers": _cfg.n_gpu_layers,
        "n_batch": _cfg.n_batch,
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
    }

@app.on_event("shutdown")
def _shutdown():
    _close_llm()

def _sigterm(_signum, _frame):
    try:
        _close_llm()
    finally:
        os._exit(0)  # fast exit to release VRAM
signal.signal(signal.SIGTERM, _sigterm)

# ---------- ONE streaming route using your existing pipeline ----------
@app.post("/api/worker/generate/stream")
async def worker_generate_stream(request: Request, data: ChatBody = Body(...)) -> StreamingResponse:
    if _llm is None:
        raise HTTPException(status_code=503, detail="Model not ready")
    # Run your full pipeline INSIDE the worker
    return await generate_stream_flow(data, request)

# Cancel stays local to the worker process
@app.post("/api/worker/cancel/{session_id}")
async def worker_cancel(session_id: str):
    return await _cancel(session_id)

@app.post("/api/worker/shutdown")
def worker_shutdown():
    try:
        _close_llm()
    finally:
        os._exit(0)
