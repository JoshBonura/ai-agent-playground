# aimodel/file_read/deps/auth_deps.py
from __future__ import annotations

import os
from typing import Any

from fastapi import Cookie, Header, HTTPException, Request

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
    # 1) Prefer fb_id cookie
    if fb_id_cookie:
        try:
            claims = await verify_jwt_with_google(fb_id_cookie)  # ✅ await
            if not isinstance(claims, dict) or not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            log.error("[auth] cookie verify error (fb_id)", extra={"err": str(e)})
        except Exception as e:
            log.error("[auth] cookie verify error (fb_id)", extra={"err": str(e)})

    # 2) Fallback to legacy cookie
    if fb_session_cookie:
        try:
            claims = await verify_jwt_with_google(fb_session_cookie)  # ✅ await
            if not isinstance(claims, dict) or not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            log.error("[auth] legacy cookie verify error", extra={"err": str(e)})
        except Exception as e:
            log.error("[auth] legacy cookie verify error", extra={"err": str(e)})

    # 3) Authorization: Bearer <token>
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1].strip()
        try:
            claims = await verify_jwt_with_google(token)  # ✅ await
            if not isinstance(claims, dict) or not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            log.error("[auth] bearer verify error", extra={"err": str(e)})
            raise
        except Exception as e:
            log.error("[auth] bearer verify error", extra={"err": str(e)})
            raise HTTPException(401, "Invalid token")

    # No valid auth presented
    raise HTTPException(401, "Not authenticated")
