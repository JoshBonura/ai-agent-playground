from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import base64, json, os, stat, sys, time
import httpx
from fastapi import HTTPException
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# ===== App paths / config =====

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

# migration from older location
_old = Path(os.path.expanduser("~/.localmind/license.json"))
if _old.exists() and not LIC_PATH.exists():
    try:
        print(f"[license] migrate old -> {LIC_PATH}")
        LIC_PATH.write_text(_old.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            _old.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception as e:
            print(f"[license] migrate unlink warn {e!r}")
    except Exception as e:
        print(f"[license] migrate error {e!r}")

LIC_PUB_HEX = os.getenv("LIC_ED25519_PUB_HEX", "").strip()
print(f"[license] using file {LIC_PATH}")
print(f"[license] pubkey set={bool(LIC_PUB_HEX)}")

COOLDOWN_SEC = 0                     # change if you want throttle
EXP_SOON_SEC = 30 * 24 * 3600        # 30 days

# ===== Internals =====

def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _verify(lic: str) -> dict:
    print("[license] _verify: start")
    if not lic or not lic.startswith("LM1."):
        print("[license] _verify: bad_format")
        raise ValueError("Bad format")
    try:
        _, payload_b64, sig_b64 = lic.split(".", 2)
    except ValueError:
        print("[license] _verify: malformed_token")
        raise ValueError("Malformed")
    payload = _b64u_decode(payload_b64)
    sig = _b64u_decode(sig_b64)
    if not LIC_PUB_HEX:
        print("[license] _verify: missing_public_key")
        raise ValueError("Verifier not configured")
    vk = VerifyKey(bytes.fromhex(LIC_PUB_HEX))
    try:
        vk.verify(payload, sig)
    except BadSignatureError:
        print("[license] _verify: bad_signature")
        raise ValueError("Invalid signature")
    data = json.loads(payload.decode("utf-8"))
    if "plan" not in data:
        data["plan"] = "pro"
    now = int(time.time())
    exp = int(data.get("exp") or 0)
    if exp and now > exp:
        print(f"[license] _verify: expired exp={exp} now={now}")
        raise ValueError("Expired")
    print("[license] _verify: ok")
    return data

def _save_secure(path: Path, obj: dict):
    print(f"[license] _save_secure: path={path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as e:
        print(f"[license] _save_secure: chmod_warn {e!r}")

def _load_current() -> dict | None:
    exists = LIC_PATH.exists()
    print(f"[license] _load_current: file={LIC_PATH} exists={exists}")
    if not exists:
        return None
    with open(LIC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _lic_base() -> str:
    base = (os.getenv("LIC_SERVER_BASE") or "").strip()
    print(f"[license] _lic_base: {base or 'MISSING'}")
    if not base:
        raise HTTPException(500, "LIC_SERVER_BASE not configured")
    return base.rstrip("/")

def _throttle_ok(kind: str) -> bool:
    now = int(time.time())
    rec: Dict[str, Any] = {}
    try:
        with open(THROTTLE_PATH, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        rec = {}
    last = int(rec.get(kind) or 0)
    if now - last < COOLDOWN_SEC:
        print(f"[license] throttle: skip kind={kind} last={last} now={now}")
        return False
    rec[kind] = now
    THROTTLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(THROTTLE_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, THROTTLE_PATH)
    print(f"[license] throttle: ok kind={kind} now={now}")
    return True

def email_from_auth(auth_payload: dict | None) -> str:
    if not auth_payload:
        return ""
    email = (auth_payload.get("email") or "").strip().lower()
    return email if "@" in email else ""

def apply_license_string(license_str: str) -> dict:
    claims = _verify(license_str.strip())
    _save_secure(LIC_PATH, {"license": license_str.strip(), "claims": claims})
    return {"ok": True, "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}

def license_status_local(expected_email: str | None = None) -> dict:
    rec = _load_current()
    if not rec:
        return {"plan": "free", "valid": False, "exp": None}

    try:
        claims = _verify(rec["license"])   # raises if invalid/expired
        plan = claims.get("plan", "pro")
        exp  = int(claims.get("exp") or 0) or None
        sub  = _canon_email(claims.get("sub"))

        if expected_email and sub and sub != _canon_email(expected_email):
            # License belongs to a different user → treat as free for this session
            return {"plan": "free", "valid": False, "exp": None, "mismatch": True}

        return {"plan": plan, "valid": True, "exp": exp, "sub": sub}
    except Exception:
        return {"plan": "free", "valid": False, "exp": None}

async def fetch_license_by_session(session_id: str) -> dict:
    base = _lic_base()
    url = f"{base}/api/license/by-session"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"session_id": session_id}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        txt = r.text[:300]
        print(f"[license] by-session: error_body={txt!r}")
        raise HTTPException(r.status_code, r.text)
    return r.json()

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
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"email": email}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = r.json() or {}
    lic = data.get("license") or ""
    if not lic:
        return {"ok": True, "status": "not_found"}
    claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": claims})
    return {"ok": True, "status": "installed", "plan": claims.get("plan", "pro"), "exp": claims.get("exp")}

def remove_license_file() -> dict:
    try:
        if LIC_PATH.exists():
            LIC_PATH.unlink()
            print("[license] delete: removed")
        else:
            print("[license] delete: not_exists")
        return {"ok": True}
    except Exception as e:
        print(f"[license] delete: error {e!r}")
        raise HTTPException(500, f"Could not remove license: {e}")

async def refresh_license(email: str, force: bool) -> dict:
    email = _canon_email(email)
    rec = _load_current()
    if not rec:
        # no local file → try recover by this email
        return await recover_by_email(email)

    try:
        claims = _verify(rec["license"])
        sub = _canon_email(claims.get("sub"))
        now = int(time.time())
        exp = int(claims.get("exp") or 0)
        plan = claims.get("plan", "pro")

        # If installed license belongs to another user, try replacing with this user's license.
        if email and sub and sub != email:
            got = await recover_by_email(email)   # may install new license or return not_found
            if (got or {}).get("status") == "installed":
                # installed a new license → report updated/new status
                st = license_status_local(expected_email=email)
                return {"ok": True, "status": "updated", **st}
            # no license for this email → report free for this user
            return {"ok": True, "status": "not_found", "plan": "free"}

        # normal freshness check
        if not force and exp and exp - now > EXP_SOON_SEC:
            return {"ok": True, "status": "fresh_enough", "plan": plan, "exp": exp}
    except Exception as e:
        # local verify failed → try recover by this email
        return await recover_by_email(email)

    if not force and not _throttle_ok("refresh"):
        return {"ok": True, "status": "skipped_cooldown"}

    # ask server for this email
    base = _lic_base()
    url = f"{base}/api/license/by-customer"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"email": email}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)

    data = r.json() or {}
    lic = data.get("license") or ""
    if not lic:
        return {"ok": True, "status": "not_found", "plan": "free"}

    new_claims = _verify(lic)
    _save_secure(LIC_PATH, {"license": lic, "claims": new_claims})
    return {"ok": True, "status": "updated", "plan": new_claims.get("plan", "pro"), "exp": new_claims.get("exp")}


def read_license_claims() -> dict:
    """Return the raw signed claims saved alongside the installed license."""
    rec = _load_current()
    if not rec:
        raise HTTPException(404, "No license installed")
    # Verify again to ensure the file hasn't gone stale/corrupted
    _ = _verify(rec["license"])
    # We store {"license": <LM1...>, "claims": {...}} when saving
    claims = rec.get("claims") or {}
    if not isinstance(claims, dict) or not claims:
        # Fallback: parse from token if needed
        try:
            _, payload_b64, _ = rec["license"].split(".", 2)
            payload = _b64u_decode(payload_b64)
            claims = json.loads(payload.decode("utf-8")) or {}
        except Exception:
            claims = {}
    return claims
