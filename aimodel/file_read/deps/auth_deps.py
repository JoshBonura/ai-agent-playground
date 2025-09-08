from __future__ import annotations
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException, Cookie, Request
from ..services.auth_service import verify_jwt_with_google  # adjust import path to your layout

ID_COOKIE_NAME = "fb_id"
LEGACY_COOKIE_NAME = "fb_session"

def require_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    fb_id_cookie: Optional[str] = Cookie(None, alias=ID_COOKIE_NAME),
    fb_session_cookie: Optional[str] = Cookie(None, alias=LEGACY_COOKIE_NAME),
) -> Dict[str, Any]:
    if fb_id_cookie:
        try:
            claims = verify_jwt_with_google(fb_id_cookie)
            if not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            print(f"[auth] cookie verify error: {e!r}")
        except Exception as e:
            print(f"[auth] cookie verify error: {e!r}")

    if fb_session_cookie:
        try:
            claims = verify_jwt_with_google(fb_session_cookie)
            if not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            print(f"[auth] legacy cookie verify error: {e!r}")
        except Exception as e:
            print(f"[auth] legacy cookie verify error: {e!r}")

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(None, 1)[1]
        try:
            claims = verify_jwt_with_google(token)
            if not claims.get("email"):
                raise HTTPException(401, "Email missing")
            return claims
        except HTTPException as e:
            print(f"[auth] bearer verify error: {e!r}")
            raise
        except Exception as e:
            print(f"[auth] bearer verify error: {e!r}")
            raise HTTPException(401, "Invalid token")

    raise HTTPException(401, "Not authenticated")
