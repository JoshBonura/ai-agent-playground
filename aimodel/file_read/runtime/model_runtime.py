# aimodel/file_read/model_runtime.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional, List
from ..adaptive.config.paths import read_settings, write_settings

try:
    from llama_cpp import Llama
except Exception as e:
    raise RuntimeError("llama-cpp-python not installed or GPU libs missing") from e

@dataclass
class ModelConfig:
    modelPath: str
    nCtx: int = 4096
    nThreads: int = 8
    nGpuLayers: int = 40
    nBatch: int = 256
    ropeFreqBase: Optional[float] = None
    ropeFreqScale: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ModelConfig":
        return ModelConfig(
            modelPath=str(d.get("modelPath","")).strip(),
            nCtx=int(d.get("nCtx", 4096)),
            nThreads=int(d.get("nThreads", 8)),
            nGpuLayers=int(d.get("nGpuLayers", 40)),
            nBatch=int(d.get("nBatch", 256)),
            ropeFreqBase=(float(d["ropeFreqBase"]) if d.get("ropeFreqBase") not in (None,"") else None),
            ropeFreqScale=(float(d["ropeFreqScale"]) if d.get("ropeFreqScale") not in (None,"") else None),
        )

_runtime_lock = RLock()
_llm: Optional[Llama] = None
_cfg: Optional[ModelConfig] = None

def _build_kwargs(cfg: ModelConfig) -> Dict[str, Any]:
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
        try:
            t = getattr(llm, "get_timings", None)
            if callable(t):
                v = t()
                if isinstance(v, dict):
                    return v
        except Exception:
            pass
        try:
            v = getattr(llm, "timings", None)
            if isinstance(v, dict):
                return v
        except Exception:
            pass
        try:
            v = getattr(llm, "perf", None)
            if isinstance(v, dict):
                return v
        except Exception:
            pass
        return None
    try:
        setattr(llm, "get_last_timings", get_last_timings)
    except Exception:
        pass

def _close_llm():
    global _llm
    try:
        if _llm is not None:
            _llm = None
    except Exception:
        _llm = None

def current_model_info() -> Dict[str, Any]:
    with _runtime_lock:
        return {
            "loaded": _llm is not None,
            "config": asdict(_cfg) if _cfg else None,
        }

def ensure_ready() -> None:
    global _llm, _cfg
    with _runtime_lock:
        if _llm is not None:
            return
        s = read_settings()
        cfg = ModelConfig.from_dict(s)
        if not cfg.modelPath:
            raise RuntimeError("No model selected. Load one via /models/load or set LOCALAI_MODEL_PATH.")
        p = Path(cfg.modelPath)
        if not p.exists():
            raise FileNotFoundError(f"Model path not found: {p}")
        _llm = Llama(**_build_kwargs(cfg))
        _attach_introspection(_llm)
        _cfg = cfg

def get_llm() -> Llama:
    ensure_ready()
    assert _llm is not None
    return _llm

def load_model(config_patch: Dict[str, Any]) -> Dict[str, Any]:
    global _llm, _cfg
    with _runtime_lock:
        s = read_settings()
        s.update({k:v for k,v in config_patch.items() if v is not None})
        cfg = ModelConfig.from_dict(s)
        if not cfg.modelPath:
            raise ValueError("modelPath is required")
        if not Path(cfg.modelPath).exists():
            raise FileNotFoundError(f"Model not found: {cfg.modelPath}")
        _close_llm()
        _llm = Llama(**_build_kwargs(cfg))
        _attach_introspection(_llm)
        _cfg = cfg
        write_settings(asdict(cfg))
        return current_model_info()

def unload_model() -> None:
    global _llm
    with _runtime_lock:
        _close_llm()

def list_local_models() -> List[Dict[str, Any]]:
    s = read_settings()
    root = Path(s.get("modelsDir") or "")
    root.mkdir(parents=True, exist_ok=True)
    out: List[Dict[str, Any]] = []
    for p in root.rglob("*.gguf"):
        try:
            out.append({
                "path": str(p.resolve()),
                "sizeBytes": p.stat().st_size,
                "name": p.name,
                "rel": str(p.relative_to(root)),
            })
        except Exception:
            pass
    out.sort(key=lambda x: x["sizeBytes"], reverse=True)
    return out
