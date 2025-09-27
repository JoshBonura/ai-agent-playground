from __future__ import annotations

import time
from fastapi import Depends, HTTPException

from ..core.request_ctx import get_user_email
from ..services.licensing_core import email_from_auth, license_status_local
from ..services.licensing_service import (
    get_activation_status,
    refresh_activation,
    remove_activation_file,
)
from .admin_deps import require_admin as _require_admin
from .auth_deps import require_auth

PRO_PLANS = {"pro", "enterprise"}


def _is_plan_pro(st: dict) -> bool:
    return bool(st.get("valid")) and (str(st.get("plan", "")).lower() in PRO_PLANS)


def has_personal_pro(email: str | None) -> bool:
    email = (email or "").strip().lower()
    st = license_status_local(expected_email=email if email else None)
    return _is_plan_pro(st)


async def _ensure_device_active() -> None:
    """
    Require local activation token. If close to expiry, try refreshing.
    If the licensing server rejects (401/403/404), delete the local token.
    """
    st = get_activation_status()
    if not st.get("present"):
        raise HTTPException(403, "Device not activated")

    now = int(time.time())
    exp = int(st.get("exp") or 0)
    needs_refresh = (not exp) or (exp - now < 7 * 24 * 3600)

    if needs_refresh:
        try:
            await refresh_activation()
        except HTTPException as e:
            if e.status_code in (401, 403, 404):
                remove_activation_file()
                raise HTTPException(403, "Device activation revoked")


# ---------- Exported FastAPI dependencies ----------

async def require_activation(user=Depends(require_auth)):
    """
    Device-scoped Pro: requires this device to be activated.
    Any authenticated user on this device passes.
    """
    await _ensure_device_active()
    return user


# Back-compat alias (some modules import require_pro)
require_pro = require_activation


async def require_personal_pro(user=Depends(require_auth)):
    """
    Personal Pro only (no device activation check).
    Use for actions tied to the user's own subscription.
    """
    email = email_from_auth(user)
    if not has_personal_pro(email):
        raise HTTPException(403, "Personal Pro required")
    return user


async def require_personal_pro_activated(user=Depends(require_auth)):
    """
    Personal Pro + Activated device (no admin). Use for RAG/Web endpoints.
    """
    email = email_from_auth(user)
    if not has_personal_pro(email):
        raise HTTPException(403, "Personal Pro required")
    await _ensure_device_active()
    return user


async def require_admin(user=Depends(_require_admin)):
    return user


async def require_admin_personal_pro(user=Depends(_require_admin)):
    """
    Admin + Personal Pro (NO device activation).
    Use when the action is admin-scoped but shouldn't force device activation.
    """
    email = email_from_auth(user)
    if not has_personal_pro(email):
        raise HTTPException(403, "Personal Pro required for admin action")
    return user


async def require_admin_pro(user=Depends(_require_admin)):
    """
    Admin + Personal Pro + Activated device.
    """
    email = email_from_auth(user)
    if not has_personal_pro(email):
        raise HTTPException(403, "Personal Pro required for admin action")
    await _ensure_device_active()
    return user


def is_request_pro_activated() -> bool:
    """
    Synchronous check for code paths that can't use FastAPI Depends.
    Requires BOTH: device activation AND personal Pro for the current request user.
    """
    try:
        # Device must be activated
        if not get_activation_status().get("present"):
            return False
        # Caller must be Pro (use request context email if available)
        email = (get_user_email() or "").strip().lower()
        return has_personal_pro(email)
    except Exception:
        return False
