# aimodel/file_read/paths.py
from __future__ import annotations
import json, os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional
import sys

# App data dir (override with LOCALAI_DATA_DIR for dev/electron)
def app_data_dir() -> Path:
    override = os.getenv("LOCALAI_DATA_DIR")
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

SETTINGS_PATH = app_data_dir() / "settings.json"

DEFAULTS = {
    "modelsDir": str((app_data_dir() / "models").resolve()),
    "modelPath": "",            # empty = none selected
    "nCtx": 4096,
    "nThreads": 8,
    "nGpuLayers": 40,
    "nBatch": 256,
    "ropeFreqBase": None,       # advanced (optional)
    "ropeFreqScale": None,      # advanced (optional)
}

def bootstrap() -> None:
    ad = app_data_dir()
    ad.mkdir(parents=True, exist_ok=True)
    md = Path(DEFAULTS["modelsDir"])
    md.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def read_settings() -> Dict[str, Any]:
    # precedence: ENV > settings.json > defaults
    bootstrap()
    cfg = DEFAULTS | _read_json(SETTINGS_PATH)

    # ENV overrides (optional)
    env_model = os.getenv("LOCALAI_MODEL_PATH")
    if env_model:
        cfg["modelPath"] = env_model

    for key, env in [
        ("modelsDir", "LOCALAI_MODELS_DIR"),
        ("nCtx", "LOCALAI_CTX"),
        ("nThreads", "LOCALAI_THREADS"),
        ("nGpuLayers", "LOCALAI_GPU_LAYERS"),
        ("nBatch", "LOCALAI_BATCH"),
        ("ropeFreqBase", "LOCALAI_ROPE_BASE"),
        ("ropeFreqScale", "LOCALAI_ROPE_SCALE"),
    ]:
        v = os.getenv(env)
        if v is not None and v != "":
            try:
                cfg[key] = int(v) if key in {"nCtx","nThreads","nGpuLayers","nBatch"} else float(v) if key in {"ropeFreqBase","ropeFreqScale"} else v
            except Exception:
                cfg[key] = v

    return cfg

def write_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = read_settings()
    cfg.update({k:v for k,v in patch.items() if v is not None})
    SETTINGS_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
