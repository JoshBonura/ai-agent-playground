# aimodel/file_read/deps/auth_deps.py
from __future__ import annotations

import os
from typing import Any

from fastapi import Cookie, Header, HTTPException, Request, status

from ..core.logging import get_logger
from ..services.auth_service import verify_jwt_with_google

log = get_logger(__name__)

ID_COOKIE_NAME = "fb_id"
LEGACY_COOKIE_NAME = "fb_session"
AUTH_ORG_ID = (os.getenv("AUTH_ORG_ID") or "").strip() or None


async def require_auth(
    request: Request,
    authorization: str | None = Header(None),
    fb_id_cookie: str | None = Cookie(None, alias=ID_COOKIE_NAME),
    fb_session_cookie: str | None = Cookie(None, alias=LEGACY_COOKIE_NAME),
) -> dict[str, Any]:
    # ---- Dev bypass (local only) ----
    if os.getenv("DEV_AUTH_BYPASS", "").lower() in ("1", "true", "yes"):
        user = {"email": "dev@local", "user_id": "dev", "sub": "dev"}
        request.state.auth_error_reason = "BYPASS_DEV"
        return user

    reasons: list[str] = []

    async def _try(token: str, origin: str) -> dict[str, Any] | None:
        try:
            claims = await verify_jwt_with_google(token)
            if not isinstance(claims, dict) or not claims.get("email"):
                reasons.append(f"{origin}:NO_EMAIL")
                return None
            # Optional org gate
            if AUTH_ORG_ID and str(claims.get("org_id") or "").strip() != AUTH_ORG_ID:
                reasons.append(f"{origin}:ORG_MISMATCH")
                return None
            return claims
        except HTTPException as e:  # your verifier may raise HTTPException(401, "…")
            # Common: TOKEN_EXPIRED / INVALID_SIGNATURE / INVALID_AUD, etc.
            reasons.append(f"{origin}:{e.detail or 'HTTP_401'}")
            log.debug("[auth] verify error (%s): %s", origin, e.detail)
            return None
        except Exception as e:
            reasons.append(f"{origin}:INVALID:{type(e).__name__}")
            log.debug("[auth] verify exception (%s): %r", origin, e)
            return None

    # 1) First-choice: fb_id cookie
    if fb_id_cookie:
        claims = await _try(fb_id_cookie, f"cookie:{ID_COOKIE_NAME}")
        if claims:
            return claims

    # 2) Legacy fallback cookie
    if fb_session_cookie:
        claims = await _try(fb_session_cookie, f"cookie:{LEGACY_COOKIE_NAME}")
        if claims:
            return claims

    # 3) Authorization: Bearer <token>
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1].strip()
        if token:
            claims = await _try(token, "authz:bearer")
            if claims:
                return claims
        else:
            reasons.append("authz:bearer:EMPTY")

    # No valid auth presented or all attempts failed
    request.state.auth_error_reason = ";".join(reasons) if reasons else "NO_CREDENTIALS"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=request.state.auth_error_reason)
