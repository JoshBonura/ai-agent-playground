from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from fastapi import HTTPException

from ..core.logging import get_logger
from .licensing_core import APP_DIR, _lic_base, _lic_post_json, _save_secure, current_license_string

log = get_logger(__name__)

# -----------------------------
# Activation paths / constants
# -----------------------------

ACT_PATH = APP_DIR / "activation.json"
APP_SALT = "lm-local-salt-v1"  # rotate to force re-activation for all devices

# -----------------------------
# Device id & local storage
# -----------------------------

def _machine_id() -> str:
    """Platform-specific, privacy-safe ID. Falls back to persistent GUID in APP_DIR."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["wmic", "csproduct", "get", "uuid"], text=True)
            vals = [ln.strip() for ln in out.splitlines() if ln.strip() and "UUID" not in ln.upper()]
            if vals:
                return vals[0]
        elif sys.platform == "darwin":
            out = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True)
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        else:
            p = Path("/etc/machine-id")
            if p.exists():
                return p.read_text().strip()
    except Exception:
        pass

    p = APP_DIR / "device.guid"
    if not p.exists():
        p.write_text(os.urandom(16).hex(), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def remove_activation_file() -> None:
    try:
        if ACT_PATH.exists():
            ACT_PATH.unlink()
    except Exception:
        pass


def device_id() -> str:
    mid = _machine_id()
    return hashlib.sha256((mid + APP_SALT).encode("utf-8")).hexdigest()


def _load_activation() -> dict | None:
    if not ACT_PATH.exists():
        return None
    try:
        return json.loads(ACT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def current_device_info() -> dict:
    """
    Handy helper for logging/UX. No network.
    """
    did = device_id()
    rec = _load_activation() or {}
    exp = int(rec.get("exp") or 0) or None
    host = platform.node() or ""
    return {
        "id": did,
        "platform": sys.platform,
        "hostname": host,
        "appVersion": os.getenv("APP_VERSION", ""),
        "activation_present": bool(rec.get("activation_token")),
        "activation_exp": exp,
    }


def get_activation_status() -> dict:
    rec = _load_activation() or {}
    exp = int(rec.get("exp") or 0) or None
    now = int(time.time())
    return {
        "present": bool(rec.get("activation_token")),
        "exp": exp,
        "stale": bool(exp and exp < now),
        "deviceId": device_id(),  # convenient for logs/UI
    }

# -----------------------------
# Network calls
# -----------------------------

async def redeem_activation(license_str: str, device_name: str = "") -> dict:
    """
    One-time per device activation with the licensing server.
    """
    base = _lic_base()
    url = f"{base}/api/activate"
    body = {
        "license": license_str.strip(),
        "device": {
            "id": device_id(),
            "platform": sys.platform,
            "appVersion": os.getenv("APP_VERSION", ""),
            "name": device_name or platform.node() or "",
        },
    }
    data = await _lic_post_json(url, body=body)
    token = (data or {}).get("activation") or ""
    if token:
        _save_secure(ACT_PATH, {"activation_token": token, "exp": data.get("exp")})
    return data


async def refresh_activation() -> dict:
    """
    Rolling refresh: re-issue activation using the stored license.
    If no local license, 404 so caller can no-op.
    """
    lic = (current_license_string() or "").strip()
    if not lic:
        raise HTTPException(404, "license_not_present")

    base = _lic_base()
    url = f"{base}/api/activate"
    body = {
        "license": lic,
        "device": {
            "id": device_id(),
            "platform": sys.platform,
            "appVersion": os.getenv("APP_VERSION", ""),
            "name": platform.node() or "",
        },
    }
    data = await _lic_post_json(url, body=body)
    token = (data or {}).get("activation") or ""
    if token:
        _save_secure(ACT_PATH, {"activation_token": token, "exp": data.get("exp")})
    return data
