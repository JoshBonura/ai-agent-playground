from __future__ import annotations

import json
from threading import RLock
from typing import Any

from ..core.logging import get_logger

log = get_logger(__name__)
from .files import (DEFAULTS_SETTINGS_FILE, OVERRIDES_SETTINGS_FILE,
                    load_json_file, save_json_file)


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    out = dict(dst)
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class _SettingsManager:
    """
    Sources of truth:
      - defaults:    read-only from DEFAULTS_SETTINGS_FILE
      - overrides:   persisted to OVERRIDES_SETTINGS_FILE
      - adaptive:    in-memory (per-session or global)
    Effective settings are computed on the fly: defaults <- adaptive <- overrides.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._defaults: dict[str, Any] = self._load_defaults()
        self._overrides: dict[str, Any] = self._load_overrides()
        self._adaptive_by_session: dict[str, dict[str, Any]] = {}

    # ----- I/O -----
    def _load_defaults(self) -> dict[str, Any]:
        return load_json_file(DEFAULTS_SETTINGS_FILE, default={})

    def _load_overrides(self) -> dict[str, Any]:
        return load_json_file(OVERRIDES_SETTINGS_FILE, default={})

    def _save_overrides_unlocked(self) -> None:
        save_json_file(OVERRIDES_SETTINGS_FILE, self._overrides)

    # ----- Effective -----
    def _effective_unlocked(self, session_id: str | None = None) -> dict[str, Any]:
        eff = _deep_merge(
            self._defaults, self._adaptive_by_session.get(session_id or "_global_", {})
        )
        eff = _deep_merge(eff, self._overrides)
        return eff

    def _get_unlocked(self, key: str, default: Any = None, *, session_id: str | None = None) -> Any:
        eff = self._effective_unlocked(session_id)
        if key in eff:
            return eff[key]
        if default is not None:
            return default
        raise AttributeError(f"_SettingsManager has no key '{key}'")

    # ----- Public API -----
    @property
    def defaults(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._defaults))

    @property
    def overrides(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._overrides))

    def adaptive(self, session_id: str | None = None) -> dict[str, Any]:
        key = session_id or "_global_"
        with self._lock:
            return json.loads(json.dumps(self._adaptive_by_session.get(key, {})))

    def effective(self, session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            return self._effective_unlocked(session_id)

    def __getattr__(self, name: str) -> Any:
        with self._lock:
            return self._get_unlocked(name)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._get_unlocked(key)

    def get(self, key: str, default: Any = None, *, session_id: str | None = None) -> Any:
        with self._lock:
            try:
                return self._get_unlocked(key, default=default, session_id=session_id)
            except AttributeError:
                return default

    # ----- Mutations -----
    def patch_overrides(self, patch: dict[str, Any]) -> None:
        if not isinstance(patch, dict):
            return
        with self._lock:
            self._overrides = _deep_merge(self._overrides, patch)
            self._save_overrides_unlocked()

    def replace_overrides(self, new_overrides: dict[str, Any]) -> None:
        if not isinstance(new_overrides, dict):
            new_overrides = {}
        with self._lock:
            self._overrides = json.loads(json.dumps(new_overrides))
            self._save_overrides_unlocked()

    def reload_overrides(self) -> None:
        with self._lock:
            self._overrides = self._load_overrides()

    def set_adaptive_for_session(self, session_id: str | None, values: dict[str, Any]) -> None:
        key = session_id or "_global_"
        if not isinstance(values, dict):
            values = {}
        with self._lock:
            self._adaptive_by_session[key] = json.loads(json.dumps(values))

    def recompute_adaptive(self, session_id: str | None = None) -> None:
        # Kept for API compatibility; effective is always computed on demand.
        return None


SETTINGS = _SettingsManager()
