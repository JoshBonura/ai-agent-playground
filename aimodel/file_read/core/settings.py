from __future__ import annotations

import json
from threading import RLock
from typing import Any

from ..core.logging import get_logger
from .files import (
    DEFAULTS_SETTINGS_FILE,
    OVERRIDES_SETTINGS_FILE,
    load_json_file,
    save_json_file,
)

log = get_logger(__name__)



def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    out = dict(dst)
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class _SettingsManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._defaults: dict[str, Any] = self._load_defaults()
        self._overrides: dict[str, Any] = self._load_overrides()
        self._adaptive_by_session: dict[str, dict[str, Any]] = {}
        log.info("[settings] init: defaults=%d keys, overrides=%d keys",
                 len(self._defaults), len(self._overrides))

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
        # lightweight trace for hardware-related keys
        wd = (eff.get("worker_default") or {})
        hb = eff.get("hw_backend")
        log.debug("[settings.effective] session=%s hw_backend=%r worker_default.accel=%r n_gpu_layers=%r device=%r",
                  session_id, hb, wd.get("accel"), wd.get("n_gpu_layers"), wd.get("device"))
        return eff

    def _get_unlocked(
        self, key: str, default: Any = None, *, session_id: str | None = None
    ) -> Any:
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
        def merge_delete(dst: dict, src: dict) -> dict:
            out = dict(dst)
            for k, v in (src or {}).items():
                if v is None:
                    out.pop(k, None)
                elif isinstance(v, dict) and isinstance(out.get(k), dict):
                    out[k] = merge_delete(out[k], v)
                else:
                    out[k] = v
            return out

        if not isinstance(patch, dict):
            return
        with self._lock:
            log.info("[settings.patch] incoming keys=%s", list(patch.keys()))
            self._overrides = merge_delete(self._overrides, patch)
            self._save_overrides_unlocked()
            log.info("[settings.patch] now overrides keys=%s", list(self._overrides.keys()))


    def replace_overrides(self, new_overrides: dict[str, Any]) -> None:
            if not isinstance(new_overrides, dict):
                new_overrides = {}
            with self._lock:
                log.info("[settings.replace] replacing overrides with %d keys", len(new_overrides))
                self._overrides = json.loads(json.dumps(new_overrides))
                self._save_overrides_unlocked()
                log.info("[settings.replace] now overrides keys=%s", list(self._overrides.keys()))


SETTINGS = _SettingsManager()
