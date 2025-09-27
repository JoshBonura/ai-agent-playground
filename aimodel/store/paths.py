# aimodel/file_read/paths.py
from __future__ import annotations
import json, os, sys
from pathlib import Path
from typing import Any
from ..core.logging import get_logger

log = get_logger(__name__)

# App data dir (override with LOCALAI_DATA_DIR or LOCALMIND_DATA_DIR)
def app_data_dir() -> Path:
    # NEW: accept either env var (LOCALAI_DATA_DIR or LOCALMIND_DATA_DIR)
    override = os.getenv("LOCALAI_DATA_DIR") or os.getenv("LOCALMIND_DATA_DIR")
    if override:
        return Path(override)

    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "LocalAI"

    if sys.platform == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "LocalAI"

    if os.name == "posix":  # Linux/other UNIX
        return Path.home() / ".local" / "share" / "LocalAI"

    return Path.home() / ".localai"

# ===== NEW: canonical runtime locations =====
def runtime_home() -> Path:
    """Base folder that holds ports.json, venvs/, accel.json, etc."""
    return app_data_dir() / ".runtime"

def runtime_ports_path() -> Path:
    return runtime_home() / "ports.json"

def runtime_venvs_dir() -> Path:
    return runtime_home() / "venvs"

def runtime_active_json() -> Path:
    return runtime_venvs_dir() / "active.json"

def accel_json_path() -> Path:
    return runtime_home() / "accel.json"

SETTINGS_PATH = app_data_dir() / "settings.json"

DEFAULTS = {
    "modelsDir": str((app_data_dir() / "models").resolve()),
    "modelPath": "",
    "nCtx": 4096,
    "nThreads": 8,
    "nGpuLayers": 40,
    "nBatch": 256,
    "ropeFreqBase": None,
    "ropeFreqScale": None,
}

def bootstrap() -> None:
    ad = app_data_dir()
    ad.mkdir(parents=True, exist_ok=True)
    # NEW: ensure .runtime exists too
    runtime_home().mkdir(parents=True, exist_ok=True)

    md = Path(DEFAULTS["modelsDir"])
    md.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")

def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def read_settings() -> dict[str, Any]:
    bootstrap()
    cfg = DEFAULTS | _read_json(SETTINGS_PATH)
    # … (unchanged below)
    # (keep your existing ENV overrides)
    # ...
    return cfg

def write_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cfg = read_settings()
    cfg.update({k: v for k, v in patch.items() if v is not None})
    SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
