# aimodel/file_read/core/files.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.logging import get_logger

log = get_logger(__name__)

CORE_DIR = Path(__file__).resolve().parent
STORE_DIR = CORE_DIR.parent / "store"

EFFECTIVE_SETTINGS_FILE = Path(
    os.getenv("EFFECTIVE_SETTINGS_PATH", str(STORE_DIR / "effective_settings.json"))
)
OVERRIDES_SETTINGS_FILE = Path(
    os.getenv("OVERRIDES_SETTINGS_PATH", str(STORE_DIR / "override_settings.json"))
)
DEFAULTS_SETTINGS_FILE = Path(
    os.getenv("DEFAULT_SETTINGS_PATH", str(STORE_DIR / "default_settings.json"))
)


def load_json_file(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {} if default is None else default


def save_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
