from __future__ import annotations
import json, os, sys
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    from ..store.paths import app_data_dir
except Exception:
    # very defensive fallback
    def app_data_dir() -> Path:
        p = Path(os.getenv("LOCALMIND_DATA_DIR", Path.home() / ".localmind"))
        p.mkdir(parents=True, exist_ok=True)
        (p / ".runtime").mkdir(parents=True, exist_ok=True)
        return p

ACCEL_FILE = app_data_dir() / ".runtime" / "accel.json"

@dataclass
class AccelPref:
    accel: str = "auto"            # "auto" | "cpu" | "cuda" | "metal" | "rocm"
    n_gpu_layers: int | None = None  # None = let worker choose; 0 => CPU

def _load() -> dict:
    try:
        return json.loads(ACCEL_FILE.read_text("utf-8"))
    except Exception:
        return {}

def read_pref() -> AccelPref:
    j = _load()
    return AccelPref(
        accel=str(j.get("accel", "auto")).lower(),
        n_gpu_layers=j.get("n_gpu_layers", None),
    )

def write_pref(p: AccelPref) -> None:
    ACCEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCEL_FILE.write_text(json.dumps(asdict(p), indent=2), encoding="utf-8")

def detect_backends() -> dict:
    out = {
        "platform": sys.platform,
        "cuda": {"available": False, "device_count": 0},
        "metal": {"available": sys.platform == "darwin"},
        "rocm": {"available": False},
    }
    # CUDA via pynvml
    try:
        import pynvml
        pynvml.nvmlInit()
        out["cuda"]["available"] = True
        out["cuda"]["device_count"] = pynvml.nvmlDeviceGetCount()
        pynvml.nvmlShutdown()
        return out
    except Exception:
        pass

    # Fallback: nvidia-smi
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=1.0)
        if r.returncode == 0 and r.stdout:
            lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("GPU ")]
            if lines:
                out["cuda"]["available"] = True
                out["cuda"]["device_count"] = len(lines)
    except Exception:
        pass

    # ROCm quick check
    try:
        if sys.platform.startswith("linux"):
            out["rocm"]["available"] = any(Path(p).exists() for p in ("/opt/rocm", "/usr/local/rocm"))
    except Exception:
        pass

    return out
