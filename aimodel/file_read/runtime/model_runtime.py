from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from ..adaptive.config.paths import read_settings
from ..core.logging import get_logger

log = get_logger(__name__)
_runtime_lock = RLock()

# Kept only for compatibility with places that import ModelConfig
@dataclass
class ModelConfig:
    modelPath: str = ""
    nCtx: int = 4096
    nThreads: int = 8
    nGpuLayers: int = 40
    nBatch: int = 256
    ropeFreqBase: float | None = None
    ropeFreqScale: float | None = None


def current_model_info() -> dict[str, Any]:
    # Main process never owns a model now
    with _runtime_lock:
        return {
            "loaded": False,
            "config": None,
            "loading": False,
            "loadingPath": None,
        }


def ensure_ready() -> None:
    # The worker process patches this to a no-op inside the worker.
    raise RuntimeError("In-process model runtime is disabled. Use a model worker.")


def get_llm():
    # The worker process patches this to return its Llama instance.
    raise RuntimeError("In-process model runtime is disabled. Use a model worker.")


def load_model(*_args, **_kwargs):
    # Block any attempt to load in the main process
    raise RuntimeError("Loading models in the main process is disabled. Spawn a worker instead.")


def unload_model() -> None:
    # Nothing to do; main process never holds VRAM now
    log.info("[model] unload requested (no-op; main runtime disabled)")


def request_cancel_load() -> bool:
    # No in-process loading means nothing to cancel
    return False


def list_local_models() -> list[dict[str, Any]]:
    import re
    try:
        from gguf import GGUFReader
    except Exception:
        GGUFReader = None  # degrade gracefully

    def read_ctx(p: Path) -> int | None:
        if GGUFReader is None:
            return None
        try:
            r = GGUFReader(str(p))
            kv = r.get_kv_data()
            # primary key used by llama.cpp-based arches (Qwen/Mistral/Llama/etc.)
            v = kv.get("llama.context_length")
            return int(v) if v is not None else None
        except Exception:
            return None

    s = read_settings()
    root = Path(s.get("modelsDir") or (Path.home() / ".localmind" / "models"))
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning(f"[model] Could not create models dir {root}: {e}")

    def guess_arch(name: str) -> str | None:
        n = name.lower()
        for c in ["qwen2.5","qwen2","qwen3","qwen","mixtral","mistral","llama","gemma","phi","yi","orca","vicuna"]:
            if c in n: return c
        return None

    def guess_params_b(name: str) -> int | None:
        m = re.search(r'(^|[^a-z0-9])(\d{1,3})\s*[bB]([^a-z0-9]|$)', name)
        return int(m.group(2)) if m else None

    def guess_quant(name: str) -> str | None:
        m = re.search(r'Q\d[A-Z0-9_]*', name)
        return m.group(0) if m else None

    out: list[dict[str, Any]] = []
    try:
        for p in root.rglob("*.gguf"):
            try:
                st = p.stat()
                name = p.name
                out.append({
                    "path": str(p.resolve()),
                    "sizeBytes": st.st_size,
                    "name": name,
                    "rel": str(p.relative_to(root)),
                    "mtime": st.st_mtime,
                    "arch": guess_arch(name),
                    "paramsB": guess_params_b(name),
                    "quant": guess_quant(name),
                    "format": "GGUF",
                    "ctxTrain": read_ctx(p),   # ← NEW
                })
            except Exception:
                pass
    except Exception:
        pass

    out.sort(key=lambda x: x["sizeBytes"], reverse=True)
    return out