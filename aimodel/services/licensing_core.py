from __future__ import annotations

import base64
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from ..core.http import ExternalServiceError, arequest_json
from ..core.logging import get_logger

log = get_logger(__name__)

# ------------------------------------------------------------------------------
# Paths / constants
# ------------------------------------------------------------------------------

def _canon_email(s: str | None) -> str:
    return (s or "").strip().lower()


def _app_data_dir() -> Path:
    """
    Cross-platform app data root. Can be overridden with LOCALMIND_DATA_DIR.
    """
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

# Migrate legacy path (best-effort, ignore errors)
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

log.info(f"[license] using file {LIC_PATH}")

COOLDOWN_SEC = 0                    # throttle window for refresh calls
EXP_SOON_SEC = 30 * 24 * 3600       # consider license “fresh enough” if >30d left


def _pubkey_hex() -> str:
    """
    Public key (ed25519) used to verify LM1 tokens. Provided via env.
    """
    return (os.getenv("LIC_ED25519_PUB_HEX") or "").strip()


# ------------------------------------------------------------------------------
# Helpers: file IO, encoding, verification
# ------------------------------------------------------------------------------

def current_license_string() -> str:
    rec = _load_current() or {}
    s = (rec.get("license") or "").strip()
    return s


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _verify(lic: str) -> dict:
    """
    Verify an LM1.<payload>.<sig> token:
      - correct shape
      - signature valid (ed25519)
      - not expired
    Returns parsed payload dict on success; raises ValueError on failure.
    """
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

    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError

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
    """
    Atomic write + best-effort 0600 perms.
    """
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
    """
    Licensing API base. Must be set in env LIC_SERVER_BASE.
    """
    base = (os.getenv("LIC_SERVER_BASE") or "").strip()
    log.info(f"[license] _lic_base: {base or 'MISSING'}")
    if not base:
        raise HTTPException(500, "LIC_SERVER_BASE not configured")
    return base.rstrip("/")


def _throttle_ok(kind: str) -> bool:
    """
    Simple per-kind cooldown to avoid hammering the licensing server.
    """
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


# ------------------------------------------------------------------------------
# Public license ops (local)
# ------------------------------------------------------------------------------

def apply_license_string(license_str: str) -> dict:
    """
    Verify and persist locally.
    """
    claims = _verify(license_str.strip())
    _save_secure(LIC_PATH, {"license": license_str.strip(), "claims": claims})
    return {"ok": True, "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}


def license_status_local(expected_email: str | None = None) -> dict:
    """
    Return local license status:
      { plan, valid, exp, sub?, mismatch? }
    """
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


def remove_license_file() -> dict:
    """
    Delete local license.json and (best effort) activation.json too.
    """
    try:
        if LIC_PATH.exists():
            LIC_PATH.unlink()
            log.info("[license] delete: removed")
        else:
            log.info("[license] delete: not_exists")

        # also try deleting activation file, if the module exists
        try:
            from .licensing_service import ACT_PATH as _ACT_PATH  # lazy import
            if _ACT_PATH.exists():
                _ACT_PATH.unlink()
        except Exception:
            pass

        return {"ok": True}
    except Exception as e:
        log.error(f"[license] delete: error {e!r}")
        raise HTTPException(500, f"Could not remove license: {e}")


# ------------------------------------------------------------------------------
# Licensing server calls
# ------------------------------------------------------------------------------

async def _lic_get_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    GET via shared arequest_json helper; maps transport errors into HTTPException.
    """
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


async def _lic_post_json(url: str, *, body: dict) -> dict[str, Any]:
    """
    POST helper. Our arequest_json signature in this app doesn't accept a JSON kw,
    so we attempt several names; if none work, fall back to raw httpx.
    """
    common_kwargs = ("json", "data", "payload", "body")
    last_err: Exception | None = None

    for kw in common_kwargs:
        try:
            log.info(f"[_lic_post_json] trying kw={kw} body={body}")
            return await arequest_json(
                method="POST",
                url=url,
                service="licensing",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                **{kw: body},
            )
        except TypeError as e:
            log.warning(f"[_lic_post_json] kw={kw} failed with {e!r}")
            last_err = e
            continue

    # FINAL FALLBACK: plain httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        # Bubble up status codes so callers can react (e.g., 403 device_limit_reached)
        raise HTTPException(e.response.status_code, e.response.text) from e
    except Exception as e:
        raise HTTPException(502, f"licensing POST failed: {e}") from e


async def fetch_license_by_session(session_id: str) -> dict:
    base = _lic_base()
    url = f"{base}/api/license/by-session"
    return await _lic_get_json(url, params={"session_id": session_id})


async def install_from_session(session_id: str) -> dict:
    data = await fetch_license_by_session(session_id)
    lic = (data or {}).get("license") or ""
    if not lic:
        raise HTTPException(404, "License not available yet")
    claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": claims})
    return {"ok": True, "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}


async def recover_by_email(email: str) -> dict:
    """
    Try to pull license associated with this email from the licensing server and install it.
    """
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
    return {"ok": True, "status": "installed", "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}


async def refresh_license(email: str, force: bool) -> dict:
    """
    Keep local license fresh:
      - If none installed: attempt recover_by_email(email)
      - If installed and not close to exp (unless force): short-circuit
      - If email mismatch: try to recover for that email
      - Otherwise fetch latest license for the customer and replace
    """
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

        # License on disk belongs to a different user than the logged-in one
        if email and sub and (sub != email):
            got = await recover_by_email(email)
            if (got or {}).get("status") == "installed":
                st = license_status_local(expected_email=email)
                return {"ok": True, "status": "updated", **st}
            return {"ok": True, "status": "not_found", "plan": "free"}

        # If we still have plenty of time and not forcing, skip network call
        if not force and exp and (exp - now > EXP_SOON_SEC):
            return {"ok": True, "status": "fresh_enough", "plan": plan, "exp": exp}

    except Exception:
        # Local token corrupt/expired → try recover
        return await recover_by_email(email)

    if not force and (not _throttle_ok("refresh")):
        return {"ok": True, "status": "skipped_cooldown"}

    # Pull latest license for this customer
    base = _lic_base()
    url = f"{base}/api/license/by-customer"
    data = await _lic_get_json(url, params={"email": email})

    lic = (data or {}).get("license") or ""
    if not lic:
        return {"ok": True, "status": "not_found", "plan": "free"}

    new_claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": new_claims})
    return {"ok": True, "status": "updated", "plan": new_claims.get("plan", "pro"), "exp": new_claims.get("exp")}
