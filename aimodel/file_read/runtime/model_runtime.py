# aimodel/file_read/runtime/model_runtime.py
from __future__ import annotations
import os, gc
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from ..adaptive.config.paths import read_settings, write_settings
from ..core.logging import get_logger

log = get_logger(__name__)

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
        return {"loaded": _llm is not None, "config": asdict(_cfg) if _cfg else None}

def ensure_ready() -> None:
    global _llm, _cfg, _loading
    with _runtime_lock:
        if _llm is not None:
            return
        if not AUTO_ON_DEMAND:
            raise RuntimeError("No model is loaded. Load one via POST /api/models/load.")
        if _loading:
            raise RuntimeError("A model load is already in progress. Try again shortly.")
        _loading = True
        try:
            s = read_settings()
            cfg = ModelConfig.from_dict(s)
            if not cfg.modelPath:
                raise RuntimeError("No model selected in settings; POST /api/models/load first.")
            p = Path(cfg.modelPath)
            if not p.exists():
                raise FileNotFoundError(f"Model path not found: {p}")
            llm = Llama(**_build_kwargs(cfg))
            _attach_introspection(llm)
            _cfg = cfg
            globals()["_llm"] = llm
            log.info(f"[model] On-demand loaded: {cfg.modelPath}")
        finally:
            _loading = False

def get_llm() -> Llama:
    ensure_ready()
    assert _llm is not None
    return _llm

def load_model(config_patch: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    """Explicit load via API; replaces any existing model safely.
       Supports resetDefaults / reset_defaults to ignore saved settings and
       fall back to ModelConfig defaults for everything except modelPath.
    """
    global _llm, _cfg, _loading
    with _runtime_lock:
        if _loading:
            raise RuntimeError("A model load is already in progress.")
        _loading = True
        try:
            patch: dict[str, Any] = dict(config_patch or {})
            if kwargs:
                patch.update(kwargs)

            # handle camelCase or snake_case
            reset = bool(patch.pop("resetDefaults", False) or patch.pop("reset_defaults", False))

            base = {} if reset else read_settings()
            # apply incoming patch over base
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
            llm = Llama(**_build_kwargs(cfg))
            _attach_introspection(llm)
            globals()["_llm"] = llm
            _cfg = cfg
            write_settings(asdict(cfg))
            log.info(f"[model] Loaded: {cfg.modelPath} (resetDefaults={reset})")
            return current_model_info()
        finally:
            _loading = False

def unload_model() -> None:
    with _runtime_lock:
        _close_llm()
        log.info("[model] Unloaded")


def list_local_models() -> list[dict[str, Any]]:
    """List *.gguf with extra metadata for UI."""
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
