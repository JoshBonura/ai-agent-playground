# aimodel/file_read/core/admins.py
from __future__ import annotations

from datetime import UTC, datetime

from ..store.base import (APP_DIR, read_json_encrypted_org,
                          write_json_encrypted_org)
from .logging import get_logger

log = get_logger(__name__)

SEC_DIR = APP_DIR / "security"
SEC_DIR.mkdir(parents=True, exist_ok=True)


# Single-admin record (not a list)
ADMIN_PATH = SEC_DIR / "admin.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------- Single admin (encrypted, org-wide) ----------


def _load_admin() -> dict | None:
    if not ADMIN_PATH.exists():
        return None
    try:
        return read_json_encrypted_org(APP_DIR, ADMIN_PATH)
    except Exception as e:
        log.error(f"[admin] failed to read admin file: {e!r}")
        return None


def _save_admin(obj: dict):
    write_json_encrypted_org(APP_DIR, ADMIN_PATH, obj)


def has_admin() -> bool:
    return _load_admin() is not None


def get_admin() -> dict | None:
    """
    Returns: {"uid": str, "email": str, "setAt": str, "guestEnabled": bool} or None
    """
    return _load_admin()


def set_admin(uid: str, email: str):
    """
    Set the single admin if (and only if) none exists yet.
    """
    if has_admin():
        # do nothing if admin already exists
        return
    rec = {
        "v": 1,
        "uid": (uid or "").strip(),
        "email": (email or "").strip().lower(),
        "setAt": _now(),
        "guestEnabled": False,
    }
    _save_admin(rec)


def is_admin(uid: str | None) -> bool:
    if not uid:
        return False
    adm = _load_admin()
    return bool(adm and adm.get("uid") == uid)


# ---------- Guest mode toggle ----------


def get_guest_enabled() -> bool:
    adm = _load_admin()
    return bool(adm and adm.get("guestEnabled"))


def set_guest_enabled(enabled: bool):
    adm = _load_admin() or {}
    if not adm:
        # no admin set → ignore
        return
    adm["guestEnabled"] = bool(enabled)
    adm.setdefault("v", 1)
    _save_admin(adm)


__all__ = [
    "get_admin",
    "get_guest_enabled",
    "has_admin",
    "is_admin",
    "set_admin",
    "set_guest_enabled",
]
