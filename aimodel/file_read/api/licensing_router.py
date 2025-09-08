from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ..deps.auth_deps import require_auth
from ..services.licensing_service import (
    apply_license_string,
    license_status_local,
    recover_by_email,
    refresh_license,
    fetch_license_by_session,
    install_from_session as svc_install_from_session,
    remove_license_file,
    email_from_auth,
    read_license_claims
)

router = APIRouter(prefix="/api/license", tags=["license"])

class ApplyReq(BaseModel):
    license: str

@router.post("/apply")
def apply_license(body: ApplyReq):
    print("[license] POST /apply")
    return apply_license_string(body.license)

@router.get("/apply")
def apply_license_get(license: str = Query(..., min_length=10)):
    print("[license] GET /apply")
    return apply_license_string(license)

@router.get("/status")
def status(user=Depends(require_auth)):  # <-- remove decorator dependencies=[]
    email = (user.get("email") or "").strip().lower()
    st = license_status_local(expected_email=email)   # <-- pass expected_email
    return st if st else {"plan": "free", "valid": False}

@router.get("/claims", dependencies=[Depends(require_auth)])
def claims():
    print("[license] GET /claims")
    st = license_status_local()
    if not st.get("valid"):
        raise HTTPException(404, "No license installed")
    return st

@router.delete("/", dependencies=[Depends(require_auth)])
def remove_license():
    print("[license] DELETE /api/license")
    return remove_license_file()

@router.get("/by-session", dependencies=[Depends(require_auth)])
async def license_by_session(session_id: str = Query(..., min_length=6)):
    print(f"[license] GET /by-session session_id={session_id}")
    return await fetch_license_by_session(session_id)

@router.post("/install-from-session", dependencies=[Depends(require_auth)])
async def install_from_session(session_id: str = Query(..., min_length=6)):
    print(f"[license] POST /install-from-session session_id={session_id}")
    return await svc_install_from_session(session_id)

@router.post("/recover")
async def recover(auth=Depends(require_auth)):
    email = email_from_auth(auth)
    print(f"[license] POST /recover email={email or 'MISSING'}")
    if not email:
        raise HTTPException(400, "Email required")
    return await recover_by_email(email)

@router.post("/refresh")
async def refresh(auth=Depends(require_auth), force: bool = Query(False)):
    print(f"[license] POST /refresh force={force}")
    email = email_from_auth(auth)
    return await refresh_license(email, force)

@router.get("/claims", dependencies=[Depends(require_auth)])
def claims():
    # Now returns the raw license claims (license_id, sub, entitlements, issued_at, exp, plan, etc.)
    return read_license_claims()
