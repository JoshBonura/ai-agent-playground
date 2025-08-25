# aimodel/file_read/core/settings.py
from __future__ import annotations

import json
from threading import RLock
from typing import Any, Dict, Optional

from .files import (
    DEFAULTS_SETTINGS_FILE,
    OVERRIDES_SETTINGS_FILE,
    EFFECTIVE_SETTINGS_FILE,
    load_json_file,
    save_json_file,
)


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst)
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


class _SettingsManager:
    """
    layers: defaults → adaptive(session/_global_) → overrides
    also persists the merged *global* effective to EFFECTIVE_SETTINGS_FILE
    (that’s what memory.py watches/loads)

    Dynamic access:
      - Attribute style: SETTINGS.stream_queue_maxsize
      - Dict style:      SETTINGS["stream_queue_maxsize"]
      - Safe get:        SETTINGS.get("stream_queue_maxsize", 64)

    Only keys present in the merged effective map are exposed dynamically.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._defaults: Dict[str, Any] = self._load_defaults()
        self._overrides: Dict[str, Any] = self._load_overrides()
        self._adaptive_by_session: Dict[str, Dict[str, Any]] = {}
        # write initial effective so memory.py has something on boot
        self._persist_effective_unlocked()

    # ---------- loading ----------
    def _load_defaults(self) -> Dict[str, Any]:
        return load_json_file(DEFAULTS_SETTINGS_FILE, default={})

    def _load_overrides(self) -> Dict[str, Any]:
        return load_json_file(OVERRIDES_SETTINGS_FILE, default={})

    # ---------- saving ----------
    def _save_overrides_unlocked(self) -> None:
        save_json_file(OVERRIDES_SETTINGS_FILE, self._overrides)

    def _persist_effective_unlocked(self) -> None:
        # Persist *global* effective (session-less) for memory.py
        eff = _deep_merge(self._defaults, self._adaptive_by_session.get("_global_", {}))
        eff = _deep_merge(eff, self._overrides)
        save_json_file(EFFECTIVE_SETTINGS_FILE, eff)

    # ---------- helpers ----------
    def _effective_unlocked(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        eff = _deep_merge(self._defaults, self._adaptive_by_session.get(session_id or "_global_", {}))
        eff = _deep_merge(eff, self._overrides)
        return eff

    def _get_unlocked(self, key: str, default: Any = None, *, session_id: Optional[str] = None) -> Any:
        eff = self._effective_unlocked(session_id)
        if key in eff:
            return eff[key]
        if default is not None:
            return default
        raise AttributeError(f"_SettingsManager has no key '{key}'")

    # ---------- public read API ----------
    @property
    def defaults(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._defaults))

    @property
    def overrides(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._overrides))

    def adaptive(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        key = session_id or "_global_"
        with self._lock:
            return json.loads(json.dumps(self._adaptive_by_session.get(key, {})))

    def effective(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            return self._effective_unlocked(session_id)

    # Dynamic attribute access (e.g., SETTINGS.stream_queue_maxsize)
    def __getattr__(self, name: str) -> Any:
        # Only called if normal attributes/methods aren't found
        with self._lock:
            return self._get_unlocked(name)

    # Dict-style access (e.g., SETTINGS["stream_queue_maxsize"])
    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._get_unlocked(key)

    # Safe getter (optional default)
    def get(self, key: str, default: Any = None, *, session_id: Optional[str] = None) -> Any:
        with self._lock:
            try:
                return self._get_unlocked(key, default=default, session_id=session_id)
            except AttributeError:
                return default

    # ---------- public write API ----------
    def patch_overrides(self, patch: Dict[str, Any]) -> None:
        if not isinstance(patch, dict):
            return
        with self._lock:
            self._overrides = _deep_merge(self._overrides, patch)
            self._save_overrides_unlocked()
            self._persist_effective_unlocked()

    def replace_overrides(self, new_overrides: Dict[str, Any]) -> None:
        if not isinstance(new_overrides, dict):
            new_overrides = {}
        with self._lock:
            self._overrides = json.loads(json.dumps(new_overrides))
            self._save_overrides_unlocked()
            self._persist_effective_unlocked()

    def reload_overrides(self) -> None:
        with self._lock:
            self._overrides = self._load_overrides()
            self._persist_effective_unlocked()

    def set_adaptive_for_session(self, session_id: Optional[str], values: Dict[str, Any]) -> None:
        key = session_id or "_global_"
        if not isinstance(values, dict):
            values = {}
        with self._lock:
            self._adaptive_by_session[key] = json.loads(json.dumps(values))
            # If updating the global adaptive layer, refresh persisted effective
            if key == "_global_":
                self._persist_effective_unlocked()

    def recompute_adaptive(self, session_id: Optional[str] = None) -> None:
        # placeholder for your controller logic later
        with self._lock:
            # after recompute, also refresh persisted effective for global
            self._persist_effective_unlocked()


SETTINGS = _SettingsManager()
