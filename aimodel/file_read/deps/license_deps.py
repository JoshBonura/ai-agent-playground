# aimodel/file_read/deps/license_deps.py
from __future__ import annotations

from fastapi import Depends, HTTPException

from ..services.licensing_service import email_from_auth, license_status_local
from .admin_deps import require_admin as _require_admin
from .auth_deps import require_auth

PRO_PLANS = {"pro", "enterprise"}


def _is_plan_pro(st: dict) -> bool:
    return bool(st.get("valid")) and (st.get("plan", "").lower() in PRO_PLANS)


def has_personal_pro(email: str | None) -> bool:
    email = (email or "").strip().lower()
    st = license_status_local(expected_email=email if email else None)
    return _is_plan_pro(st)


async def require_pro(user=Depends(require_auth)):
    email = email_from_auth(user)
    if has_personal_pro(email):
        return user
    raise HTTPException(403, "Pro license required")


async def require_admin_pro(user=Depends(_require_admin)):
    """
    Admin gate: caller must be the admin AND personally Pro.
    """
    email = email_from_auth(user)
    if has_personal_pro(email):
        return user
    raise HTTPException(403, "Pro license required for admin")
