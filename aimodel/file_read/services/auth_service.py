# ===== aimodel/file_read/services/auth_service.py =====
from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)

import json
import os
import time
from typing import Any

from fastapi import HTTPException
from jose import jwt as jose_jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from ..core.http import ExternalServiceError, arequest_json

_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
_CERTS_TTL = 60 * 60  # 1 hour
_CERTS_CACHE: dict[str, Any] = {"k2pem": {}, "fetched_at": 0}


def _get_api_key() -> str:
    v = (os.getenv("FIREBASE_WEB_API_KEY") or "").strip()
    if not v:
        # Keep this an error so it’s obvious in logs
        log.error("[auth] ERROR: FIREBASE_WEB_API_KEY not set")
    return v


def _get_project_id() -> str:
    v = (os.getenv("FIREBASE_PROJECT_ID") or "").strip()
    if not v:
        log.error("[auth] ERROR: FIREBASE_PROJECT_ID is not set")
    return v


def need_project_check() -> bool:
    return _get_project_id() == ""


async def fetch_google_certs_async() -> dict[str, str]:
    """Fetch and cache Google public certs used to verify Firebase ID tokens."""
    now = int(time.time())
    if now - int(_CERTS_CACHE.get("fetched_at") or 0) < _CERTS_TTL:
        return _CERTS_CACHE["k2pem"]

    try:
        data = await arequest_json(
            method="GET",
            url=_CERTS_URL,
            service="google_certs",
            headers={"Accept": "application/json"},
        )
        if isinstance(data, dict):
            _CERTS_CACHE["k2pem"] = data
            _CERTS_CACHE["fetched_at"] = now
            log.info(f"[auth] fetched Google certs; kids={list(data.keys())[:3]}...")
            return data
    except ExternalServiceError as e:
        log.error(f"[auth] ERROR fetching Google certs: status={e.status} detail={e.detail!r}")
    except Exception as e:
        log.error(f"[auth] ERROR fetching Google certs: {e!r}")

    return _CERTS_CACHE.get("k2pem", {})


async def verify_jwt_with_google(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token using Google x509 certs (async)."""
    proj = _get_project_id()
    if not proj:
        raise HTTPException(500, "Auth not configured")

    try:
        header = jose_jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            log.info("[auth] token header missing 'kid'")
            raise HTTPException(401, "Invalid token header")

        # Lightweight preview for logs / sanity
        payload_preview = jose_jwt.get_unverified_claims(token)
        log.debug(
            "[auth] id_token preview: %s",
            {
                "header": {"alg": header.get("alg"), "kid": kid, "typ": header.get("typ")},
                "payload": {
                    "iss": payload_preview.get("iss"),
                    "aud": payload_preview.get("aud"),
                    "email": payload_preview.get("email"),
                    "email_verified": payload_preview.get("email_verified"),
                    "uid": payload_preview.get("uid"),
                    "iat": payload_preview.get("iat"),
                    "exp": payload_preview.get("exp"),
                },
            },
        )

        certs = await fetch_google_certs_async()
        pem = certs.get(kid)
        if not pem:
            log.info(f"[auth] kid {kid} not found in certs; refreshing once")
            _CERTS_CACHE["fetched_at"] = 0
            certs = await fetch_google_certs_async()
            pem = certs.get(kid)
            if not pem:
                raise HTTPException(401, "Key not found for token")

        issuer = f"https://securetoken.google.com/{proj}"
        claims = jose_jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=proj,
            issuer=issuer,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iat": True,
                "verify_exp": True,
            },
        )
        return claims

    except ExpiredSignatureError:
        log.warning("[auth] token expired")
        raise HTTPException(401, "Token expired")
    except JWTError as e:
        log.info(f"[auth] JWTError while verifying: {e}")
        raise HTTPException(401, "Invalid token")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[auth] unexpected verify error: {e!r}")
        raise HTTPException(401, "Invalid token")


async def firebase_sign_in_with_password(email: str, password: str) -> dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(500, "Server auth not configured")

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    try:
        data = await arequest_json(
            method="POST",
            url=url,
            service="firebase_auth",
            headers={"Accept": "application/json"},
            json_body={"email": email, "password": password, "returnSecureToken": True},
        )
        log.info(f"[auth] REST login ok email={email}")
        return data
    except ExternalServiceError as e:
        msg = e.body_preview or e.detail or "Invalid credentials"
        log.error(f"[auth] REST login failed status={e.status} body={str(msg)[:200]!r}")
        raise HTTPException(401, "Invalid credentials") from e


async def firebase_sign_up_with_password(email: str, password: str) -> dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(500, "Server auth not configured")

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    try:
        data = await arequest_json(
            method="POST",
            url=url,
            service="firebase_auth",
            headers={"Accept": "application/json"},
            json_body={"email": email, "password": password, "returnSecureToken": True},
        )
        log.info(f"[auth] REST register ok email={email}")
        return data
    except ExternalServiceError as e:
        raw = (e.body_preview or "")[:200]
        msg = "Could Not Register"
        try:
            j = json.loads(e.body_preview or "{}")
            msg = (j.get("error", {}).get("message") or "").replace("_", " ").title() or msg
        except Exception:
            pass
        raise HTTPException(400, msg) from e
