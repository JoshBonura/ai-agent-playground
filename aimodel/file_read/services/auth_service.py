from __future__ import annotations
import os, time
from typing import Dict, Any
import httpx
from jose import jwt as jose_jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from fastapi import HTTPException

FIREBASE_API_KEY = (os.getenv("FIREBASE_WEB_API_KEY") or "").strip()
FIREBASE_PROJECT_ID = (os.getenv("FIREBASE_PROJECT_ID") or "").strip()

_CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
_CERTS_TTL = 60 * 60  # 1 hour
_CERTS_CACHE: Dict[str, Any] = {"k2pem": {}, "fetched_at": 0}

def need_project_check() -> bool:
    if not FIREBASE_PROJECT_ID:
        print("[auth] ERROR: FIREBASE_PROJECT_ID is not set")
        return True
    return False

def fetch_google_certs_sync() -> Dict[str, str]:
    now = int(time.time())
    if now - int(_CERTS_CACHE.get("fetched_at") or 0) < _CERTS_TTL:
        return _CERTS_CACHE["k2pem"]  # type: ignore[return-value]
    try:
        r = httpx.get(_CERTS_URL, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            _CERTS_CACHE["k2pem"] = data
            _CERTS_CACHE["fetched_at"] = now
            print(f"[auth] fetched Google certs; kids={list(data.keys())[:3]}...")
            return data
    except Exception as e:
        print(f"[auth] ERROR fetching Google certs: {e!r}")
    return _CERTS_CACHE.get("k2pem", {})  # type: ignore[return-value]

def verify_jwt_with_google(token: str) -> Dict[str, Any]:
    if need_project_check():
        raise HTTPException(500, "Auth not configured")
    try:
        header = jose_jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            print("[auth] token header missing 'kid'")
            raise HTTPException(401, "Invalid token header")

        payload_preview = jose_jwt.get_unverified_claims(token)
        print("[auth] id_token preview:", {
            "header": {"alg": header.get("alg"), "kid": kid, "typ": header.get("typ")},
            "payload": {
                "iss": payload_preview.get("iss"),
                "aud": payload_preview.get("aud"),
                "email": payload_preview.get("email"),
                "email_verified": payload_preview.get("email_verified"),
                "uid": payload_preview.get("uid"),
                "iat": payload_preview.get("iat"),
                "exp": payload_preview.get("exp"),
            }
        })

        certs = fetch_google_certs_sync()
        pem = certs.get(kid)
        if not pem:
            print(f"[auth] kid {kid} not found in certs; refreshing once")
            _CERTS_CACHE["fetched_at"] = 0
            certs = fetch_google_certs_sync()
            pem = certs.get(kid)
            if not pem:
                raise HTTPException(401, "Key not found for token")

        issuer = f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}"
        claims = jose_jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=FIREBASE_PROJECT_ID,
            issuer=issuer,
            options={"verify_signature": True, "verify_aud": True, "verify_iat": True, "verify_exp": True},
        )
        return claims
    except ExpiredSignatureError:
        print("[auth] token expired")
        raise HTTPException(401, "Token expired")
    except JWTError as e:
        print(f"[auth] JWTError while verifying: {e}")
        raise HTTPException(401, "Invalid token")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[auth] unexpected verify error: {e!r}")
        raise HTTPException(401, "Invalid token")

async def firebase_sign_in_with_password(email: str, password: str) -> Dict[str, Any]:
    if not FIREBASE_API_KEY:
        print("[auth] ERROR: FIREBASE_WEB_API_KEY not set")
        raise HTTPException(500, "Server auth not configured")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    if r.status_code >= 400:
        print(f"[auth] REST login failed status={r.status_code} body={r.text[:200]!r}")
        raise HTTPException(401, "Invalid credentials")
    data = r.json()
    print(f"[auth] REST login ok email={email}")
    return data

async def firebase_sign_up_with_password(email: str, password: str) -> Dict[str, Any]:
    if not FIREBASE_API_KEY:
        print("[auth] ERROR: FIREBASE_WEB_API_KEY not set")
        raise HTTPException(500, "Server auth not configured")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    if r.status_code >= 400:
        # Typical errors: EMAIL_EXISTS, OPERATION_NOT_ALLOWED, WEAK_PASSWORD
        try:
            j = r.json()
            msg = (j.get("error", {}).get("message") or "").replace("_", " ").title()
        except Exception:
            msg = r.text[:200]
        raise HTTPException(400, msg or "Could not register")
    data = r.json()
    print(f"[auth] REST register ok email={email}")
    return data
