# backend/.../runtime/model_runtime.py
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from ..store.paths import read_settings
from ..core.logging import get_logger

log = get_logger(__name__)

# ------------------------------------------------------------------------------
# Fast, cached model discovery (no GGUF header reads)
# ------------------------------------------------------------------------------

_CACHE: dict[str, Any] = {"etag": None, "data": None, "ts": 0.0}
_CACHE_TTL = 10.0  # seconds; throttle rebuilds a bit


def _models_root() -> Path:
    s = read_settings()
    return Path(s.get("modelsDir") or (Path.home() / ".localmind" / "models"))


def _snapshot(root: Path) -> tuple[str, list[tuple[str, int, int]]]:
    """
    Return (etag, items) where items is a stable list of (abs_path, mtime, size).
    The etag is a sha1 of this snapshot to detect changes cheaply.
    """
    items: list[tuple[str, int, int]] = []
    for p in root.rglob("*.gguf"):
        try:
            st = p.stat()
            items.append((str(p.resolve()), int(st.st_mtime), int(st.st_size)))
        except Exception:
            # ignore unreadable files
            pass
    items.sort()
    blob = json.dumps(items, separators=(",", ":")).encode("utf-8")
    etag = hashlib.sha1(blob).hexdigest()
    return etag, items


def _guess_arch(name: str) -> str | None:
    n = name.lower()
    for c in [
        "qwen2.5",
        "qwen2",
        "qwen3",
        "qwen",
        "mixtral",
        "mistral",
        "llama",
        "gemma",
        "phi",
        "yi",
        "orca",
        "vicuna",
    ]:
        if c in n:
            return c
    return None


def _guess_params_b(name: str) -> int | None:
    m = re.search(r"(^|[^a-z0-9])(\d{1,3})\s*[bB]([^a-z0-9]|$)", name)
    return int(m.group(2)) if m else None


def _guess_quant(name: str) -> str | None:
    m = re.search(r"Q\d[A-Z0-9_]*", name)
    return m.group(0) if m else None

# --- GGUF header helpers (optional dependency) ---
try:
    from gguf import GGUFReader  # pip install gguf
except Exception:
    GGUFReader = None

def _gguf_fields(path: str) -> dict[str, Any] | None:
    if GGUFReader is None:
        return None
    try:
        r = GGUFReader(path)
        # r.fields is a list of (name, value) pairs in older gguf; newer exposes .get k/v
        # Normalize to dict defensively:
        try:
            # Newer versions expose .kv_data or .fields as dict-like
            kv = dict(r.fields)  # may work if fields is iterable of pairs
        except Exception:
            kv = {}
            for k in dir(r):
                if k.startswith("get_"):
                    # skip methods; stay minimal
                    pass
        # Fallback: try known accessors
        if not kv:
            try:
                for item in r.fields:
                    try:
                        kv[item.key] = item.value
                    except Exception:
                        pass
            except Exception:
                pass
        return kv or {}
    except Exception:
        return None

def read_model_meta_from_gguf(path: str) -> dict[str, Any] | None:
    """
    Returns:
      {
        'ctxTrain': int|None,
        'nLayers': int|None,
        'nHeads': int|None,
        'arch': str|None,
        'quant': str|None
      }
    """
    fields = _gguf_fields(path)
    if fields is None:
        return None

    # Common keys across families; try a few, in order:
    def pick_int(*names: str, default: int | None = None) -> int | None:
        for n in names:
            if n in fields:
                try:
                    return int(fields[n])
                except Exception:
                    pass
        return default

    def pick_str(*names: str, default: str | None = None) -> str | None:
        for n in names:
            if n in fields:
                try:
                    v = fields[n]
                    return str(v) if v is not None else default
                except Exception:
                    pass
        return default

    ctx_train = pick_int(
        "llama.context_length",
        "general.context_length",
        "gpt.model.context_length",
        "context_length",
        default=None,
    )
    n_layers = pick_int(
        "llama.block_count",
        "general.block_count",
        "block_count",
        default=None,
    )
    n_heads = pick_int(
        "llama.attention.head_count",
        "attention.head_count",
        default=None,
    )
    arch = pick_str("general.architecture", "llama.architecture", default=None)

    # You already parse a filename quant; keep that, but header often has this:
    quant = pick_str("general.file_type", "quantization", default=None)

    return {
        "ctxTrain": ctx_train,
        "nLayers": n_layers,
        "nHeads": n_heads,
        "arch": arch,
        "quant": quant,
    }



def list_models_cached(*, with_ctx: bool = False) -> tuple[list[dict[str, Any]], str]:
    """
    Fast listing (no GGUF header reads). Returns (models, etag).
    If with_ctx=True you can later enrich with header-derived info.
    """
    now = time.time()

    # Hot cache hit (TTL not expired): return immediately
    if _CACHE.get("data") and (now - float(_CACHE.get("ts", 0.0)) < _CACHE_TTL):
        return _CACHE["data"], _CACHE["etag"]

    root = _models_root()
    etag, snap = _snapshot(root)

    # Snapshot unchanged: bump timestamp and return cached data
    if _CACHE.get("etag") == etag and _CACHE.get("data"):
        _CACHE["ts"] = now
        return _CACHE["data"], _CACHE["etag"]

    # Rebuild listing
    out: list[dict[str, Any]] = []
    for path, mtime, size in snap:
        p = Path(path)
        name = p.name
        try:
            rel = str(p.relative_to(root))  # safer than startswith on Windows
        except Exception:
            rel = name
        out.append(
            {
                "path": path,
                "sizeBytes": size,
                "name": name,
                "rel": rel,
                "mtime": mtime,
                "arch": _guess_arch(name),
                "paramsB": _guess_params_b(name),
                "quant": _guess_quant(name),
                "format": "GGUF",
                # keep key for compatibility; fill later if you want header reads
                "ctxTrain": None if not with_ctx else None,
            }
        )

    out.sort(key=lambda x: x["sizeBytes"], reverse=True)

    _CACHE.update({"etag": etag, "data": out, "ts": now})
    return out, etag


# ------------------------------------------------------------------------------
# Back-compat surface (main-process runtime is disabled; worker owns the model)
# ------------------------------------------------------------------------------

def current_model_info() -> dict[str, Any]:
    """Main process never holds a model now; keep legacy shape."""
    return {
        "loaded": False,
        "config": None,
        "loading": False,
        "loadingPath": None,
    }


def ensure_ready() -> None:
    raise RuntimeError("In-process model runtime is disabled. Use a model worker.")


def get_llm():
    raise RuntimeError("In-process model runtime is disabled. Use a model worker.")


def load_model(*_args, **_kwargs):
    raise RuntimeError("Loading models in the main process is disabled. Spawn a worker instead.")


def unload_model() -> None:
    log.info("[model] unload requested (no-op; main runtime disabled)")


def request_cancel_load() -> bool:
    return False


def list_local_models() -> list[dict[str, Any]]:
    """Legacy name; return the fast cached listing."""
    models, _ = list_models_cached(with_ctx=False)
    return models


__all__ = [
    # fast listing
    "list_models_cached",
    "list_local_models",
    # legacy surface (no-op stubs)
    "current_model_info",
    "ensure_ready",
    "get_llm",
    "load_model",
    "unload_model",
    "request_cancel_load",
]
