# aimodel/file_read/api/billing.py
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from ..core.http import ExternalServiceError, arequest_json
from ..core.logging import get_logger
from ..deps.auth_deps import require_auth as decode_bearer
from ..services.licensing_service import license_status_local

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["billing"])

LIC_SERVER = (os.getenv("LIC_SERVER_BASE") or "").rstrip("/")
if not LIC_SERVER:
    raise RuntimeError(
        "LIC_SERVER_BASE env var is required (e.g. https://lic-server.localmind.workers.dev)"
    )

SERVICE = "licensing"
ACCEPT_JSON = {"Accept": "application/json"}


@router.get("/billing/status")
async def billing_status(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")

    try:
        lic = license_status_local(expected_email=email)
        active = bool(lic.get("valid"))
        return {
            "status": "active" if active else "inactive",
            "current_period_end": int(lic.get("exp") or 0),
        }
    except Exception as e:
        # Local-only path: treat any error as inactive but log it.
        log.warning("billing_status_local_error", extra={"detail": str(e)})
        return {"status": "inactive", "current_period_end": 0}


@router.post("/billing/checkout")
async def start_checkout(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")

    url = f"{LIC_SERVER}/api/checkout/session"
    try:
        data = await arequest_json(
            method="POST",
            url=url,
            service=SERVICE,
            headers=ACCEPT_JSON,
            json_body={"email": email},
        )
    except ExternalServiceError as e:
        # Map to a sensible HTTP status. If upstream gave a status, reuse it;
        # otherwise use 504 for timeouts / gateway issues.
        status = e.status or 504
        log.warning(
            "billing_checkout_error", extra={"status": status, "url": e.url, "detail": e.detail}
        )
        raise HTTPException(status, e.detail or "Checkout failed")

    if not isinstance(data, dict) or "url" not in data:
        log.warning("billing_checkout_bad_response", extra={"url": url})
        raise HTTPException(502, "Bad response from licensing server")

    return {"url": data["url"]}


@router.post("/billing/portal")
async def open_portal(auth=Depends(decode_bearer)):
    email = (auth.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(401, "No email in token")

    url = f"{LIC_SERVER}/api/portal/session"
    try:
        data = await arequest_json(
            method="POST",
            url=url,
            service=SERVICE,
            headers=ACCEPT_JSON,
            json_body={"email": email},
        )
    except ExternalServiceError as e:
        status = e.status or 504
        log.warning(
            "billing_portal_error", extra={"status": status, "url": e.url, "detail": e.detail}
        )
        raise HTTPException(status, e.detail or "Portal session failed")

    if not isinstance(data, dict) or "url" not in data:
        log.warning("billing_portal_bad_response", extra={"url": url})
        raise HTTPException(502, "Bad response from licensing server")

    return {"url": data["url"]}


@router.get("/license/by-session")
async def license_by_session(session_id: str):
    if not session_id:
        raise HTTPException(400, "Missing session_id")

    url = f"{LIC_SERVER}/api/license/by-session"
    try:
        data = await arequest_json(
            method="GET",
            url=url,
            service=SERVICE,
            headers=ACCEPT_JSON,
            params={"session_id": session_id},
        )
    except ExternalServiceError as e:
        status = e.status or 504
        log.warning(
            "license_by_session_error", extra={"status": status, "url": e.url, "detail": e.detail}
        )
        raise HTTPException(status, e.detail or "License lookup failed")

    return data
