# aimodel/file_read/runtime/model_runtime.py
from __future__ import annotations
import os, gc
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock, Event
from typing import Any
from ..adaptive.config.paths import read_settings, write_settings
from ..core.logging import get_logger

log = get_logger(__name__)
_progress_hits = 0

try:
    from llama_cpp import Llama
except Exception as e:
    raise RuntimeError("llama-cpp-python not installed or GPU libs missing") from e

AUTO_ON_DEMAND = os.getenv("AUTO_LOAD_ON_FIRST_USE", "").lower() in ("1", "true", "yes")

@dataclass
class ModelConfig:
    modelPath: str
    nCtx: int = 4096
    nThreads: int = 8
    nGpuLayers: int = 40
    nBatch: int = 256
    ropeFreqBase: float | None = None
    ropeFreqScale: float | None = None
    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ModelConfig":
        return ModelConfig(
            modelPath=str(d.get("modelPath", "")).strip(),
            nCtx=int(d.get("nCtx", 4096)),
            nThreads=int(d.get("nThreads", 8)),
            nGpuLayers=int(d.get("nGpuLayers", 40)),
            nBatch=int(d.get("nBatch", 256)),
            ropeFreqBase=(float(d["ropeFreqBase"]) if d.get("ropeFreqBase") not in (None, "") else None),
            ropeFreqScale=(float(d["ropeFreqScale"]) if d.get("ropeFreqScale") not in (None, "") else None),
        )

_runtime_lock = RLock()
_llm: Llama | None = None
_cfg: ModelConfig | None = None
_loading: bool = False
_loading_model_path: str | None = None
_cancel_ev: Event = Event()

def _progress_cb(progress: float, *_args, **_kwargs) -> bool:
    global _progress_hits
    if _progress_hits < 5:
        _progress_hits += 1
        log.info(f"[model] progress_cb hit #{_progress_hits}: {progress:.2%}")
    return not _cancel_ev.is_set()

def _build_kwargs(cfg: ModelConfig) -> dict[str, Any]:
    kw = dict(
        model_path=cfg.modelPath,
        n_ctx=cfg.nCtx,
        n_threads=cfg.nThreads,
        n_gpu_layers=cfg.nGpuLayers,
        n_batch=cfg.nBatch,
    )
    if cfg.ropeFreqBase is not None:
        kw["rope_freq_base"] = cfg.ropeFreqBase
    if cfg.ropeFreqScale is not None:
        kw["rope_freq_scale"] = cfg.ropeFreqScale
    return kw

def _attach_introspection(llm: Llama) -> None:
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

def is_loaded() -> bool:
    with _runtime_lock:
        return _llm is not None

def current_model_info() -> dict[str, Any]:
    with _runtime_lock:
        return {
            "loaded": _llm is not None,
            "config": asdict(_cfg) if _cfg else None,
            "loading": _loading,
            "loadingPath": _loading_model_path,
        }

def request_cancel_load() -> bool:
    with _runtime_lock:
        if not _loading:
            return False
        _cancel_ev.set()
        log.info("[model] Cancellation requested for in-progress load")
        return True

def ensure_ready() -> None:
    global _llm, _cfg, _loading, _loading_model_path
    with _runtime_lock:
        if _llm is not None:
            return
        if not AUTO_ON_DEMAND:
            raise RuntimeError("No model is loaded. Load one via POST /api/models/load.")
        if _loading:
            raise RuntimeError("A model load is already in progress. Try again shortly.")

        s = read_settings()
        cfg = ModelConfig.from_dict(s)
        if not cfg.modelPath:
            raise RuntimeError("No model selected in settings; POST /api/models/load first.")
        p = Path(cfg.modelPath)
        if not p.exists():
            raise FileNotFoundError(f"Model path not found: {p}")

        _loading = True
        _loading_model_path = cfg.modelPath
        _cancel_ev.clear()
        kw = _build_kwargs(cfg)
        kw["progress_callback"] = _progress_cb

    llm = None
    try:
        if _cancel_ev.is_set():
            raise RuntimeError("CANCELLED")

        llm = Llama(**kw)
        _attach_introspection(llm)

        if _cancel_ev.is_set():
            try:
                del llm
            finally:
                gc.collect()
            with _runtime_lock:
                _loading = False
                _loading_model_path = None
            log.info("[model] Load cancelled (after init)")
            raise RuntimeError("CANCELLED")

        with _runtime_lock:
            _llm = llm
            _cfg = cfg
            log.info(f"[model] On-demand loaded: {cfg.modelPath}")
    except Exception:
        if llm is not None:
            try:
                del llm
            finally:
                gc.collect()
        raise
    finally:
        with _runtime_lock:
            _loading = False
            _loading_model_path = None
            # do NOT clear _cancel_ev here; leave it set until next load

def get_llm() -> Llama:
    ensure_ready()
    assert _llm is not None
    return _llm

def load_model(config_patch: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    global _llm, _cfg, _loading, _loading_model_path
    with _runtime_lock:
        if _loading:
            raise RuntimeError("A model load is already in progress.")

        patch: dict[str, Any] = dict(config_patch or {})
        if kwargs:
            patch.update(kwargs)

        reset = bool(patch.pop("resetDefaults", False) or patch.pop("reset_defaults", False))
        base = {} if reset else read_settings()
        for k, v in list(patch.items()):
            if v is None:
                patch.pop(k, None)
        base.update(patch)

        cfg = ModelConfig.from_dict(base)
        if not cfg.modelPath:
            raise ValueError("modelPath is required")
        if not Path(cfg.modelPath).exists():
            raise FileNotFoundError(f"Model not found: {cfg.modelPath}")

        _close_llm()

        _loading = True
        _loading_model_path = cfg.modelPath
        _cancel_ev.clear()
        kw = _build_kwargs(cfg)
        kw["progress_callback"] = _progress_cb

    if _cancel_ev.is_set():
        raise RuntimeError("CANCELLED")

    llm = Llama(**kw)
    _attach_introspection(llm)

    if _cancel_ev.is_set():
        try:
            del llm
        finally:
            gc.collect()
        with _runtime_lock:
            _loading = False
            _loading_model_path = None
        log.info("[model] Load cancelled (after init)")
        raise RuntimeError("CANCELLED")

    with _runtime_lock:
        try:
            _llm = llm
            _cfg = cfg
            write_settings(asdict(cfg))
            log.info(f"[model] Loaded: {cfg.modelPath} (resetDefaults={reset})")
            return current_model_info()
        finally:
            _loading = False
            _loading_model_path = None
            # leave _cancel_ev state alone here

def unload_model() -> None:
    with _runtime_lock:
        _close_llm()
        log.info("[model] Unloaded")

def list_local_models() -> list[dict[str, Any]]:
    import re
    s = read_settings()
    root = Path(s.get("modelsDir") or (Path.home() / ".localmind" / "models"))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning(f"[model] Could not create models dir {root}: {e}")

    def guess_arch(name: str) -> str | None:
        n = name.lower()
        for c in ["qwen2.5", "qwen2", "qwen3", "qwen", "mixtral", "mistral", "llama", "gemma", "phi", "yi", "orca", "vicuna"]:
            if c in n:
                return c
        return None

    def guess_params_b(name: str) -> int | None:
        m = re.search(r'(^|[^a-z0-9])(\d{1,3})\s*[bB]([^a-z0-9]|$)', name)
        if m:
            try:
                return int(m.group(2))
            except Exception:
                return None
        return None

    def guess_quant(name: str) -> str | None:
        m = re.search(r'Q\d[A-Z0-9_]*', name)
        return m.group(0) if m else None

    out: list[dict[str, Any]] = []
    try:
        for p in root.rglob("*.gguf"):
            try:
                st = p.stat()
                name = p.name
                out.append(
                    {
                        "path": str(p.resolve()),
                        "sizeBytes": st.st_size,
                        "name": name,
                        "rel": str(p.relative_to(root)),
                        "mtime": st.st_mtime,
                        "arch": guess_arch(name),
                        "paramsB": guess_params_b(name),
                        "quant": guess_quant(name),
                        "format": "GGUF",
                    }
                )
            except Exception:
                pass
    except Exception:
        pass

    out.sort(key=lambda x: x["sizeBytes"], reverse=True)
    return out
