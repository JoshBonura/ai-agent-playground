from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException, Depends
import httpx

from ..deps.auth_deps import require_auth as decode_bearer
from ..services.licensing_service import license_status_local  

router = APIRouter(prefix="/api", tags=["billing"])

LIC_SERVER = (os.getenv("LIC_SERVER_BASE") or "").rstrip("/")
if not LIC_SERVER:
    raise RuntimeError(
        "LIC_SERVER_BASE env var is required (e.g. https://lic-server.localmind.workers.dev)"
    )

@router.get("/billing/status")
async def billing_status(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")

    try:
        lic = license_status_local(expected_email=email)  # <-- pass expected_email
        active = bool(lic.get("valid"))
        return {
            "status": "active" if active else "inactive",
            "current_period_end": int(lic.get("exp") or 0),
        }
    except Exception:
        return {"status": "inactive", "current_period_end": 0}

@router.post("/billing/checkout")
async def start_checkout(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")
    url = f"{LIC_SERVER}/api/checkout/session"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(url, json={"email": email}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    if not isinstance(data, dict) or "url" not in data:
        raise HTTPException(502, "Bad response from licensing server")
    return {"url": data["url"]}

@router.post("/billing/portal")
async def open_portal(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")
    url = f"{LIC_SERVER}/api/portal/session"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(url, json={"email": email}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    if not isinstance(data, dict) or "url" not in data:
        raise HTTPException(502, "Bad response from licensing server")
    return {"url": data["url"]}

@router.get("/license/by-session")
async def license_by_session(session_id: str):
    if not session_id:
        raise HTTPException(400, "Missing session_id")
    url = f"{LIC_SERVER}/api/license/by-session"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params={"session_id": session_id}, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()
