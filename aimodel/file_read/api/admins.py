from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core import admins as reg
from ..deps.auth_deps import require_auth
from ..deps.license_deps import has_personal_pro, require_personal_pro, require_admin_pro

router = APIRouter(prefix="/api/admins", tags=["admins"])


class GuestToggleReq(BaseModel):
    enabled: bool


@router.get("/state")
def state(user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    email = (user.get("email") or "").lower()

    personal_pro = has_personal_pro(email)
    admin_rec = reg.get_admin()
    is_listed_admin = bool(admin_rec and admin_rec.get("uid") == uid)

    # Admin is independent of personal Pro
    is_admin = is_listed_admin

    return {
        # single-admin state
        "hasAdmin": bool(admin_rec),
        "isAdmin": is_admin,            # UI: show admin controls when True
        "isAdminRaw": is_listed_admin,  # listed as admin, regardless of Pro
        "ownerUid": (admin_rec or {}).get("uid"),
        "ownerEmail": (admin_rec or {}).get("email"),
        # guest toggle
        "guestEnabled": reg.get_guest_enabled(),
        # first Pro user can self-promote if no admin exists yet
        "canSelfPromote": (admin_rec is None) and personal_pro,
        # convenience flags for UI
        "pro": personal_pro,
        "me": {"uid": uid, "email": email, "pro": personal_pro},
    }


@router.post("/self-promote")
def self_promote(user=Depends(require_personal_pro)):
    """
    First Pro user can claim the single admin slot (no device activation required).
    """
    if reg.has_admin():
        raise HTTPException(403, "Admin already set")
    uid = user.get("user_id") or user.get("sub")
    email = (user.get("email") or "").lower()
    reg.set_admin(uid, email)
    return {"ok": True}


@router.post("/guest")
def set_guest(req: GuestToggleReq, user=Depends(require_admin_pro)):
    """
    Requires: Admin + Personal Pro + Activated device.
    """
    reg.set_guest_enabled(bool(req.enabled))
    return {"ok": True, "enabled": reg.get_guest_enabled()}
