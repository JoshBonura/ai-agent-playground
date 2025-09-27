from __future__ import annotations

# Initialize logging ASAP
from aimodel.core.logging import setup_logging, get_logger
wlog = get_logger("aimodel.worker")
wlog.info("worker logging initialized")
_progress = {"pct": 0, "hits": 0, "last_args": None}

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
    # gives you GGML_TYPE_* integer constants
    from llama_cpp import llama_cpp as C  # type: ignore
except Exception:
    C = None

try:
    from llama_cpp import Llama  # type: ignore
except Exception as e:
    raise RuntimeError("llama-cpp-python not installed in worker") from e

from aimodel.core.schemas import ChatBody
from aimodel.services.generate_flow import generate_stream_flow, cancel_session as _cancel


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


app = FastAPI(title="LocalMind Model Worker", version="0.3")

_llm: Optional[Llama] = None
_cfg: Optional[WorkerCfg] = None
_applied_kwargs: Dict[str, Any] = {}

# Requested accel from supervisor/ENV (already normalized on the API side)
# one of: auto | cpu | cuda | metal | hip
_ACCEL = (os.getenv("LLAMA_ACCEL") or "auto").lower()
_DEVICE = os.getenv("LLAMA_DEVICE")  # gpu index as string (optional)


def _supports_param(name: str) -> bool:
    """Does Llama.__init__ accept this kwarg?"""
    try:
        return name in inspect.signature(Llama.__init__).parameters
    except Exception:
        return False


def _progress_cb_any(*args, **kwargs):
    try:
        _progress["hits"] = int(_progress.get("hits", 0)) + 1
        if _progress["hits"] <= 5:
            wlog.info(f"[progress_cb] args={args} kwargs={kwargs}")

        pct: int | None = None
        if len(args) >= 2 and all(isinstance(x, (int, float)) for x in args[:2]):
            cur, tot = args[0], args[1]
            if tot:
                pct = int(max(0, min(100, (cur * 100.0) / tot)))
        elif len(args) >= 1 and isinstance(args[0], (int, float)):
            pct = int(max(0, min(100, args[0])))

        if pct is not None:
            _progress["pct"] = pct
    except Exception as e:
        wlog.warning(f"[progress_cb] error: {e}")


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

    # progress callback (name varies by build)
    try:
        init_params = set(inspect.signature(Llama.__init__).parameters.keys())
        for name in ("progress_callback", "progress"):
            if name in init_params:
                kw[name] = _progress_cb_any
                wlog.info(f"[worker] using progress callback param: {name}")
                break
        else:
            wlog.info("[worker] this Llama build exposes no progress callback param")
    except Exception as e:
        wlog.info(f"[worker] could not inspect Llama.__init__: {e}")

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
        from aimodel.runtime import model_runtime as MR
        import os

        def _ensure_ready():
            return True

        def _get_llm():
            return llm

        # NEW: capture some worker identity hints (optional envs)
        _WID  = os.getenv("WORKER_ID") or ""
        _HOST = os.getenv("WORKER_HOST") or "127.0.0.1"
        _PORT = int(os.getenv("PORT") or os.getenv("WORKER_PORT") or "0")

        def _current_model_info():
            cfg = {
                "modelPath": _cfg.model_path if _cfg else "",
                "nCtx": int(_applied_kwargs.get("n_ctx", 4096)),
                "nThreads": int(_applied_kwargs.get("n_threads", 0) or 0),
                "nGpuLayers": int(_applied_kwargs.get("n_gpu_layers", 0) or 0),
                "nBatch": int(_applied_kwargs.get("n_batch", 0) or 0),
                "ropeFreqBase": _applied_kwargs.get("rope_freq_base"),
                "ropeFreqScale": _applied_kwargs.get("rope_freq_scale"),
            }
            # NEW: include a 'worker' section
            worker = {
                "id": _WID,
                "host": _HOST,
                "port": _PORT,
                "accel": _ACCEL,
                "kwargs": {
                    **{k: v for k, v in _applied_kwargs.items() if k in {
                        "n_ctx","n_threads","n_gpu_layers","n_batch","rope_freq_base","rope_freq_scale",
                        "offload_kqv","kv_offload","main_gpu"
                    }},
                    "model_path": cfg["modelPath"],
                },
            }
            return {"config": cfg, "loading": False, "path": cfg["modelPath"], "worker": worker}

        MR.ensure_ready = _ensure_ready
        MR.get_llm = _get_llm
        MR.current_model_info = _current_model_info
        try:
            setattr(MR, "_LLM", llm)
        except Exception:
            pass
        wlog.info("patched model_runtime to use worker LLM + current_model_info")
    except Exception as e:
        wlog.warning(f"failed to patch model_runtime: {e}")



def _parse_llama_kwargs_from_env() -> Dict[str, Any]:
    raw = os.getenv("LLAMA_KWARGS_JSON") or ""
    if not raw.strip():
        wlog.info("[worker.env] LLAMA_KWARGS_JSON is empty")
        return {}
    try:
        d = json.loads(raw)
        wlog.info("[worker.env] parsed LLAMA_KWARGS_JSON keys=%s", sorted(list(d.keys())))
        return d if isinstance(d, dict) else {}
    except Exception as e:
        wlog.warning("[worker.env] failed to parse LLAMA_KWARGS_JSON: %r", e)
        return {}


def _filter_llama_kwargs(extra: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(Llama.__init__)
        allowed = set(sig.parameters.keys()) - {"self"}
        wlog.info("[worker.filter] allowed-from-signature=%s", sorted(list(allowed)))
    except Exception:
        allowed = {
            "model_path","n_ctx","n_threads","n_gpu_layers","n_batch",
            "rope_freq_base","rope_freq_scale","seed",
            "use_mmap","use_mlock",
            "flash_attn",
            "type_k","type_v",
            "main_gpu","device",
            "kv_offload","offload_kqv",
        }
        wlog.info("[worker.filter] using fallback allowed set")

    out, dropped = {}, {}
    for k, v in (extra or {}).items():
        (out if k in allowed else dropped)[k] = v

    if dropped:
        wlog.info("[worker.filter] dropped_keys=%s", sorted(list(dropped.keys())))
    return out   # <-- return the filtered dict


# add these helpers somewhere above _startup()
_STR_TO_GGML = {
    "f32":    "GGML_TYPE_F32",
    "f16":    "GGML_TYPE_F16",
    "q8_0":   "GGML_TYPE_Q8_0",
    "q4_0":   "GGML_TYPE_Q4_0",
    "q4_1":   "GGML_TYPE_Q4_1",
    "iq4_nl": "GGML_TYPE_IQ4_NL",
    "q5_0":   "GGML_TYPE_Q5_0",
    "q5_1":   "GGML_TYPE_Q5_1",
}

def _coerce_cache_type(x):
    """Map UI string like 'q4_K' to ggml enum int; return None for 'auto'/unknown."""
    if x is None:
        return None
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if not s or s.lower() == "auto":
        return None
    if C is None:
        wlog.warning("[worker.start] llama_cpp constants unavailable; ignoring type_k/type_v")
        return None
    cname = _STR_TO_GGML.get(s)
    if not cname:
        wlog.warning("[worker.start] unknown cache type %r (type_k/type_v); ignoring", s)
        return None
    val = getattr(C, cname, None)
    if not isinstance(val, int):
        wlog.warning("[worker.start] constant %s missing; ignoring", cname)
        return None
    return val

def _normalize_kv_offload(extra: Dict[str, Any]) -> Dict[str, Any]:
    # If supervisor sent kv_offload, but this wheel wants offload_kqv, translate it.
    try:
        sig = set(inspect.signature(Llama.__init__).parameters.keys())
    except Exception:
        sig = set()
    v = extra.get("kv_offload")
    if v is not None and "offload_kqv" in sig and "kv_offload" not in sig:
        extra["offload_kqv"] = bool(v)
        wlog.info("[worker.norm] mapped kv_offload=%r -> offload_kqv=%r", v, extra["offload_kqv"])
    return extra


def _apply_accel_translation(accel: str, kw: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    a = (accel or "auto").lower()

    # If user explicitly set n_gpu_layers, never override it.
    user_set_layers = ("n_gpu_layers" in kw) and (kw["n_gpu_layers"] not in (None, 0))

    if a == "cpu":
        kw["n_gpu_layers"] = 0
        kw.pop("main_gpu", None)
        kw.pop("device", None)
        return "cpu", kw

    if a in ("cuda", "metal", "hip", "auto"):
        # Only supply a default if the caller didn't set anything.
        if not user_set_layers:
            kw["n_gpu_layers"] = 999
        if _DEVICE and _DEVICE.isdigit():
            idx = int(_DEVICE)
            if _supports_param("main_gpu"):
                kw["main_gpu"] = idx
            elif _supports_param("device"):
                kw["device"] = idx
        return a, kw

    return a, kw


@app.get("/api/worker/log-test")
def _log_test():
    lg = get_logger("aimodel.worker.logtest")
    lg.debug("debug: hello from worker")
    lg.info("info: hello from worker")
    lg.warning("warn: hello from worker")
    return {"ok": True}


@app.on_event("startup")
def _startup():
    global _llm, _cfg, _applied_kwargs, _ACCEL
    _cfg = WorkerCfg.from_env()
    base_kw = _build_kwargs(_cfg)

    # merge extra kwargs (from supervisor)
    raw = _parse_llama_kwargs_from_env()
    raw = _normalize_kv_offload(raw)
    extra = _filter_llama_kwargs(raw)
    for k, v in extra.items():
        if k != "model_path":
            base_kw[k] = v

    wlog.info("[worker.start] llama supports kv_offload: %s", _supports_param("kv_offload"))
    wlog.info("[worker.start] llama supports offload_kqv: %s", _supports_param("offload_kqv"))
    wlog.info("[worker.filter] kept_keys=%s", sorted(list(extra.keys())))
    # Show what we received
    wlog.info("[worker.start] pre-translate accel=%s device=%s kwargs_in=%s",
              _ACCEL, _DEVICE, _redact(base_kw))
    wlog.info("[worker.start] kv_offload=%r (pre-translate)", base_kw.get("kv_offload"))

    # translate accel -> llama kwargs
    _ACCEL, base_kw = _apply_accel_translation(_ACCEL, base_kw)

    tk = base_kw.get("type_k", None)
    tv = base_kw.get("type_v", None)
    c_tk = _coerce_cache_type(tk)
    c_tv = _coerce_cache_type(tv)
    if c_tk is not None:
        base_kw["type_k"] = c_tk
    else:
        base_kw.pop("type_k", None)
    if c_tv is not None:
        base_kw["type_v"] = c_tv
    else:
        base_kw.pop("type_v", None)

    # Show the translation result + env that might affect it
    wlog.info("[worker.start] kv_offload=%r (post-translate)", base_kw.get("kv_offload"))
    wlog.info("[worker.start] post-translate accel=%s n_gpu_layers=%s main_gpu=%s device=%s",
              _ACCEL, base_kw.get("n_gpu_layers"), base_kw.get("main_gpu"), _DEVICE)
    wlog.info("[worker.start] env knobs: CUDA_VISIBLE_DEVICES=%s HIP_VISIBLE_DEVICES=%s LLAMA_NO_METAL=%s GGML_CUDA_NO_VMM=%s",
              os.getenv("CUDA_VISIBLE_DEVICES"), os.getenv("HIP_VISIBLE_DEVICES"),
              os.getenv("LLAMA_NO_METAL"), os.getenv("GGML_CUDA_NO_VMM"))

    _applied_kwargs = dict(base_kw)
    wlog.info("[worker.start] applied kv_offload=%r", _applied_kwargs.get("kv_offload"))
    wlog.info(f"startup cwd={os.getcwd()} py={sys.version.split()[0]}")
    wlog.info(f"MODEL_PATH={_cfg.model_path}")
    wlog.info(f"accel={_ACCEL} device={_DEVICE}")
    wlog.info(f"llama kwargs: {json.dumps(_redact(base_kw), ensure_ascii=False, default=repr)}")

    # Try to initialize. If GPU init fails, fall back to CPU.
    try:
        _llm = Llama(**base_kw)
    except Exception as e:
        if int(base_kw.get("n_gpu_layers", 0) or 0) > 0:
            wlog.warning(f"GPU/accelerated init failed; falling back to CPU. err={e!r}")
            base_kw["n_gpu_layers"] = 0
            _ACCEL = "cpu"
            _applied_kwargs = dict(base_kw)
            _llm = Llama(**base_kw)
        else:
            raise

    _attach_introspection(_llm)
    _patch_main_runtime_with_worker_llm(_llm)
    wlog.info("llama initialized OK")
    wlog.info(
    "[worker.env.id] id=%s host=%s port=%s",
    os.getenv("WORKER_ID", ""),
    os.getenv("WORKER_HOST", "127.0.0.1"),
    os.getenv("WORKER_PORT", os.getenv("PORT", ""))
)

    try:
        from aimodel.core.settings import SETTINGS as _S
        from aimodel.deps.license_deps import is_request_pro_activated as _pro
        wlog.info(
            f"worker settings: runjson_emit={bool(_S.runjson_emit)} "
            f"stream_emit_stopped_line={bool(_S.stream_emit_stopped_line)}"
        )
        wlog.info(f"worker license: pro={bool(_pro())}")
    except Exception as e:
        wlog.info(f"worker settings/license probe failed: {e}")


def _redact(kw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in kw.items():
        if callable(v):
            out[k] = f"<callable:{getattr(v, '__name__', 'fn')}>"
            continue
        try:
            json.dumps(v)
            out[k] = v
        except TypeError:
            out[k] = repr(v)
    return out


@app.get("/api/worker/health")
def worker_health():
    if _cfg is None:
        return {"ok": False}
    name = os.path.basename(_cfg.model_path)
    payload = {
        "ok": _llm is not None,
        "model": name,
        "path": _cfg.model_path,
        "accel": _ACCEL,
        "kwargs": _applied_kwargs,
        "kv_offload": (
            _applied_kwargs.get("kv_offload")
            if _applied_kwargs.get("kv_offload") is not None
            else _applied_kwargs.get("offload_kqv")
        ),
        "offload_kqv": _applied_kwargs.get("offload_kqv"),
        "n_ctx": _applied_kwargs.get("n_ctx"),
        "n_threads": _applied_kwargs.get("n_threads"),
        "n_gpu_layers": _applied_kwargs.get("n_gpu_layers"),
        "n_batch": _applied_kwargs.get("n_batch"),
        "progress": {"pct": int(_progress.get("pct", 0)), "hits": int(_progress.get("hits", 0))},
    }
    # Log summary of what we're returning
    try:
        wlog.info(
            "[worker.health] reply keys=%s kwargs=%s",
            list(payload.keys()),
            {k: (payload.get("kwargs", {}) or {}).get(k)
             for k in ("n_gpu_layers", "offload_kqv", "n_ctx", "n_batch", "n_threads")}
        )
    except Exception as e:
        wlog.warning(f"[worker.health] log fail: {e}")
    return payload


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
            "LLAMA_ACCEL": os.getenv("LLAMA_ACCEL"),
            "LLAMA_DEVICE": os.getenv("LLAMA_DEVICE"),
            "WORKER_ID": os.getenv("WORKER_ID"),
            "WORKER_HOST": os.getenv("WORKER_HOST"),
            "WORKER_PORT": os.getenv("WORKER_PORT"),
            "PORT": os.getenv("PORT"),
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
