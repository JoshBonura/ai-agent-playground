# aimodel/file_read/api/auth_router.py
from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)
import os

from fastapi import APIRouter, Depends, HTTPException, Response

from ..deps.auth_deps import require_auth
from ..services.auth_service import (firebase_sign_in_with_password,
                                     firebase_sign_up_with_password,
                                     verify_jwt_with_google)
from ..services.licensing_service import license_status_local, recover_by_email

router = APIRouter(prefix="/api")

AUTH_REQUIRE_VERIFIED = os.getenv("AUTH_REQUIRE_VERIFIED", "false").lower() == "true"
ID_COOKIE_NAME = os.getenv("AUTH_IDTOKEN_COOKIE", "fb_id")
LEGACY_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE", "fb_session")
SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "7"))
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = (os.getenv("AUTH_COOKIE_SAMESITE", "lax") or "lax").lower()
COOKIE_DOMAIN = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
COOKIE_PATH = "/"

if COOKIE_SAMESITE == "none" and (not COOKIE_SECURE):
    raise RuntimeError("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")


def _set_cookie(resp: Response, name: str, value: str, max_age_s: int):
    resp.set_cookie(
        key=name,
        value=value,
        max_age=max_age_s,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path=COOKIE_PATH,
    )


def _clear_cookie(resp: Response, name: str):
    resp.delete_cookie(key=name, domain=COOKIE_DOMAIN, path=COOKIE_PATH)


@router.post("/auth/login")
async def login(body: dict[str, str], response: Response):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "Email and password required")

    # Firebase sign-in
    data = await firebase_sign_in_with_password(email, password)
    id_token = data.get("idToken")
    if not id_token:
        raise HTTPException(401, "Login failed")

    # ✅ FIX: await the async verifier
    try:
        claims = await verify_jwt_with_google(id_token)
    except Exception as e:
        log.warning("[auth] verify_jwt_with_google failed", extra={"err": str(e)})
        raise HTTPException(401, "Invalid ID token")

    if not isinstance(claims, dict):
        log.error("[auth] verifier did not return a dict")
        raise HTTPException(401, "Invalid ID token")

    if AUTH_REQUIRE_VERIFIED and (not bool(claims.get("email_verified"))):
        raise HTTPException(401, "Email not verified")

    max_age = SESSION_DAYS * 86400
    _set_cookie(response, ID_COOKIE_NAME, id_token, max_age)
    _set_cookie(response, LEGACY_COOKIE_NAME, id_token, max_age)

    # Try to hydrate local license state (best effort)
    lic_snapshot = {"plan": "free", "valid": False, "exp": None}
    try:
        await recover_by_email(email)
        # pass expected_email to ensure we show the right license
        lic_snapshot = license_status_local(expected_email=email)
    except Exception as e:
        log.error(f"[auth] license recover after login failed: {e!r}")

    return {
        "ok": True,
        "email": email,
        "uid": claims.get("user_id") or claims.get("sub"),
        "emailVerified": bool(claims.get("email_verified")),
        "expiresInDays": SESSION_DAYS,
        "license": lic_snapshot,
    }


@router.post("/auth/logout")
def logout(response: Response):
    _clear_cookie(response, ID_COOKIE_NAME)
    _clear_cookie(response, LEGACY_COOKIE_NAME)
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(require_auth)):
    try:
        lic = license_status_local(expected_email=(user.get("email") or "").lower())
    except Exception:
        lic = {"plan": "free", "valid": False, "exp": None}

    return {
        "email": (user.get("email") or "").lower(),
        "uid": user.get("user_id") or user.get("sub"),
        "emailVerified": bool(user.get("email_verified")),
        "name": user.get("name"),
        "picture": user.get("picture"),
        "iat": user.get("iat"),
        "exp": user.get("exp"),
        "license": lic,
    }


@router.post("/auth/register")
async def register(body: dict[str, str]):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise HTTPException(400, "Email and password required")
    await firebase_sign_up_with_password(email, password)
    return {"ok": True}
