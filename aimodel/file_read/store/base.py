from __future__ import annotations
import json, os, shutil, tempfile, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from ..paths import app_data_dir

# -------- Directories & Paths --------
APP_DIR = app_data_dir()
CHATS_DIR = APP_DIR / "chats"
INDEX_PATH = APP_DIR / "index.json"
PENDING_PATH = APP_DIR / "pending.json"              # NEW
OLD_PENDING_DELETES = APP_DIR / "pending_deletes.json"  # NEW

# -------- Lock for safe writes --------
_lock = threading.RLock()

# -------- Helpers --------
def now_iso() -> str:
    """UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def atomic_write(path: Path, data: Dict[str, Any] | List[Any]):
    """Safely write JSON to a temp file then move into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        shutil.move(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def ensure_dirs():
    """Ensure app/chats directories exist and index.json is initialized."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        atomic_write(INDEX_PATH, [])

def chat_path(session_id: str) -> Path:
    """Return path to chat file for a session ID."""
    return CHATS_DIR / f"{session_id}.json"

# -------- Exports --------
__all__ = [
    "APP_DIR",
    "CHATS_DIR",
    "INDEX_PATH",
    "PENDING_PATH",          # NEW
    "OLD_PENDING_DELETES",   # NEW
    "_lock",
    "now_iso",
    "atomic_write",
    "ensure_dirs",
    "chat_path",
]
