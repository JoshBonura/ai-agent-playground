from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
import base64
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from ..core.http import ExternalServiceError, arequest_json

# -----------------------------
# Basics / paths / constants
# -----------------------------


def _canon_email(s: str | None) -> str:
    return (s or "").strip().lower()


def _app_data_dir() -> Path:
    override = os.getenv("LOCALMIND_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "LocalAI"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalAI"
    else:
        return Path.home() / ".config" / "LocalAI"


APP_DIR = _app_data_dir() / "license"
APP_DIR.mkdir(parents=True, exist_ok=True)
LIC_PATH = APP_DIR / "license.json"
THROTTLE_PATH = APP_DIR / "license.throttle.json"

# NEW: device activation local file
ACT_PATH = APP_DIR / "activation.json"

# Device-id salt (stable within an app build; rotate only if you want all devices to re-activate)
APP_SALT = "lm-local-salt-v1"

_old = Path(os.path.expanduser("~/.localmind/license.json"))
if _old.exists() and (not LIC_PATH.exists()):
    try:
        log.info(f"[license] migrate old -> {LIC_PATH}")
        LIC_PATH.write_text(_old.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            _old.unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"[license] migrate unlink warn {e!r}")
    except Exception as e:
        log.error(f"[license] migrate error {e!r}")


# NOTE: do NOT read the pubkey at import time; read it lazily at verify-time.
def _pubkey_hex() -> str:
    return (os.getenv("LIC_ED25519_PUB_HEX") or "").strip()


log.info(f"[license] using file {LIC_PATH}")
COOLDOWN_SEC = 0
EXP_SOON_SEC = 30 * 24 * 3600


# -----------------------------
# License verification helpers
# -----------------------------


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _verify(lic: str) -> dict:
    log.info("[license] _verify: start")
    if not lic or not lic.startswith("LM1."):
        log.info("[license] _verify: bad_format")
        raise ValueError("Bad format")
    try:
        _, payload_b64, sig_b64 = lic.split(".", 2)
    except ValueError:
        log.info("[license] _verify: malformed_token")
        raise ValueError("Malformed")
    payload = _b64u_decode(payload_b64)
    sig = _b64u_decode(sig_b64)

    pub = _pubkey_hex()
    if not pub:
        log.info("[license] _verify: missing_public_key")
        raise ValueError("Verifier not configured")

    vk = VerifyKey(bytes.fromhex(pub))
    try:
        vk.verify(payload, sig)
    except BadSignatureError:
        log.info("[license] _verify: bad_signature")
        raise ValueError("Invalid signature")

    data = json.loads(payload.decode("utf-8"))
    if "plan" not in data:
        data["plan"] = "pro"
    now = int(time.time())
    exp = int(data.get("exp") or 0)
    if exp and now > exp:
        log.warning(f"[license] _verify: expired exp={exp} now={now}")
        raise ValueError("Expired")
    log.info("[license] _verify: ok")
    return data


def _save_secure(path: Path, obj: dict):
    log.info(f"[license] _save_secure: path={path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as e:
        log.info(f"[license] _save_secure: chmod_warn {e!r}")


def _load_current() -> dict | None:
    exists = LIC_PATH.exists()
    log.info(f"[license] _load_current: file={LIC_PATH} exists={exists}")
    if not exists:
        return None
    with open(LIC_PATH, encoding="utf-8") as f:
        return json.load(f)


def _lic_base() -> str:
    base = (os.getenv("LIC_SERVER_BASE") or "").strip()
    log.info(f"[license] _lic_base: {base or 'MISSING'}")
    if not base:
        raise HTTPException(500, "LIC_SERVER_BASE not configured")
    return base.rstrip("/")


def _throttle_ok(kind: str) -> bool:
    now = int(time.time())
    rec: dict[str, Any] = {}
    try:
        with open(THROTTLE_PATH, encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        rec = {}
    last = int(rec.get(kind) or 0)
    if now - last < COOLDOWN_SEC:
        log.info(f"[license] throttle: skip kind={kind} last={last} now={now}")
        return False
    rec[kind] = now
    THROTTLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(THROTTLE_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, THROTTLE_PATH)
    log.info(f"[license] throttle: ok kind={kind} now={now}")
    return True


def email_from_auth(auth_payload: dict | None) -> str:
    if not auth_payload:
        return ""
    email = (auth_payload.get("email") or "").strip().lower()
    return email if "@" in email else ""


# -----------------------------
# Public license ops (existing)
# -----------------------------


def apply_license_string(license_str: str) -> dict:
    claims = _verify(license_str.strip())
    _save_secure(LIC_PATH, {"license": license_str.strip(), "claims": claims})
    return {"ok": True, "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}


def license_status_local(expected_email: str | None = None) -> dict:
    rec = _load_current()
    if not rec:
        return {"plan": "free", "valid": False, "exp": None}
    try:
        claims = _verify(rec["license"])
        plan = claims.get("plan", "pro")
        exp = int(claims.get("exp") or 0) or None
        sub = _canon_email(claims.get("sub"))
        if expected_email and sub and (sub != _canon_email(expected_email)):
            return {"plan": "free", "valid": False, "exp": None, "mismatch": True}
        return {"plan": plan, "valid": True, "exp": exp, "sub": sub}
    except Exception:
        return {"plan": "free", "valid": False, "exp": None}


async def fetch_license_by_session(session_id: str) -> dict:
    base = _lic_base()
    url = f"{base}/api/license/by-session"
    data = await _lic_get_json(url, params={"session_id": session_id})
    return data


async def _lic_get_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await arequest_json(
            method="GET",
            url=url,
            service="licensing",
            headers={"Accept": "application/json"},
            params=params or {},
        )
    except ExternalServiceError as e:
        raise HTTPException(e.status or 502, e.detail or "Licensing service error") from e


# NEW: POST helper
async def _lic_post_json(url: str, *, body: dict) -> dict[str, Any]:
    try:
        return await arequest_json(
            method="POST",
            url=url,
            service="licensing",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=body,
        )
    except ExternalServiceError as e:
        raise HTTPException(e.status or 502, e.detail or "Licensing service error") from e


async def install_from_session(session_id: str) -> dict:
    data = await fetch_license_by_session(session_id)
    lic = (data or {}).get("license") or ""
    if not lic:
        raise HTTPException(404, "License not available yet")
    claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": claims})
    return {"ok": True, "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}


async def recover_by_email(email: str) -> dict:
    if not email:
        return {"ok": True, "status": "not_found"}
    base = _lic_base()
    url = f"{base}/api/license/by-customer"

    data = await _lic_get_json(url, params={"email": email})
    lic = (data or {}).get("license") or ""
    if not lic:
        return {"ok": True, "status": "not_found"}

    claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": claims})
    return {
        "ok": True,
        "status": "installed",
        "plan": claims.get("plan", "pro"),
        "exp": claims.get("exp"),
    }


def remove_license_file() -> dict:
    try:
        if LIC_PATH.exists():
            LIC_PATH.unlink()
            log.info("[license] delete: removed")
        else:
            log.info("[license] delete: not_exists")
        # also remove activation token when license removed
        try:
            if ACT_PATH.exists():
                ACT_PATH.unlink()
        except Exception:
            pass
        return {"ok": True}
    except Exception as e:
        log.error(f"[license] delete: error {e!r}")
        raise HTTPException(500, f"Could not remove license: {e}")


async def refresh_license(email: str, force: bool) -> dict:
    email = _canon_email(email)
    rec = _load_current()
    if not rec:
        return await recover_by_email(email)
    try:
        claims = _verify(rec["license"])
        sub = _canon_email(claims.get("sub"))
        now = int(time.time())
        exp = int(claims.get("exp") or 0)
        plan = claims.get("plan", "pro")
        if email and sub and (sub != email):
            got = await recover_by_email(email)
            if (got or {}).get("status") == "installed":
                st = license_status_local(expected_email=email)
                return {"ok": True, "status": "updated", **st}
            return {"ok": True, "status": "not_found", "plan": "free"}
        if not force and exp and (exp - now > EXP_SOON_SEC):
            return {"ok": True, "status": "fresh_enough", "plan": plan, "exp": exp}
    except Exception:
        return await recover_by_email(email)

    if not force and (not _throttle_ok("refresh")):
        return {"ok": True, "status": "skipped_cooldown"}

    base = _lic_base()
    url = f"{base}/api/license/by-customer"
    data = await _lic_get_json(url, params={"email": email})

    lic = (data or {}).get("license") or ""
    if not lic:
        return {"ok": True, "status": "not_found", "plan": "free"}

    new_claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": new_claims})
    return {
        "ok": True,
        "status": "updated",
        "plan": new_claims.get("plan", "pro"),
        "exp": new_claims.get("exp"),
    }


# -----------------------------
# NEW: Device activation bits
# -----------------------------


def _machine_id() -> str:
    """
    Platform-specific, privacy-safe machine identifier.
    Falls back to a persistent random GUID inside APP_DIR.
    """
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["wmic", "csproduct", "get", "uuid"], text=True)
            vals = [
                ln.strip() for ln in out.splitlines() if ln.strip() and "UUID" not in ln.upper()
            ]
            if vals:
                return vals[0]
        elif sys.platform == "darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True
            )
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        else:
            p = Path("/etc/machine-id")
            if p.exists():
                return p.read_text().strip()
    except Exception:
        pass

    # fallback: a persistent random GUID in app dir
    p = APP_DIR / "device.guid"
    if not p.exists():
        p.write_text(os.urandom(16).hex(), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


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


def get_activation_status() -> dict:
    rec = _load_activation() or {}
    exp = int(rec.get("exp") or 0) or None
    now = int(time.time())
    return {
        "present": bool(rec.get("activation_token")),
        "exp": exp,
        "stale": bool(exp and exp < now),
    }


async def redeem_activation(license_str: str, device_name: str = "") -> dict:
    """
    One-time (per device) activation redemption with the licensing server.
    - Verifies nothing online here; server will validate the LM1 license.
    - Stores activation token locally on success.
    """
    base = _lic_base()
    url = f"{base}/api/activation/redeem"
    body = {
        "license": license_str.strip(),
        "device_id": device_id(),
        "device_name": device_name or platform.node()[:64],
        "app_version": os.getenv("APP_VERSION", ""),
    }
    data = await _lic_post_json(url, body=body)
    token = (data or {}).get("activation_token") or ""
    if token:
        _save_secure(ACT_PATH, {"activation_token": token, "exp": data.get("exp")})
    return data


async def refresh_activation() -> dict:
    """
    Rolling token refresh (e.g., 30d). If none present, raise 404 so caller can no-op.
    """
    rec = _load_activation()
    if not rec or not rec.get("activation_token"):
        raise HTTPException(404, "activation_not_present")

    base = _lic_base()
    url = f"{base}/api/activation/refresh"
    body = {
        "activation_token": rec["activation_token"],
        "device_id": device_id(),
    }
    data = await _lic_post_json(url, body=body)
    token = (data or {}).get("activation_token") or ""
    if token:
        _save_secure(ACT_PATH, {"activation_token": token, "exp": data.get("exp")})
    return data
