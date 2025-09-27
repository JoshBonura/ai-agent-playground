# aimodel/file_read/api/licensing_router.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, HTTPException
from pydantic import BaseModel

from ..deps.auth_deps import require_auth
from ..services.licensing_core import (
    apply_license_string,
    email_from_auth,
    license_status_local,
    refresh_license,
    current_license_string,
)
from ..services.licensing_service import (
    get_activation_status,
    redeem_activation,
    refresh_activation,
    remove_activation_file,
)
from ..core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/license", tags=["license"])


class ApplyReq(BaseModel):
    license: str


@router.post("/apply")
async def apply_license(body: ApplyReq, user_agent: str | None = Header(default=None)):
    """
    1) Verify and persist the LM1 license locally.
    2) Redeem a device-scoped activation token (best-effort).
    """
    log.info("[license] POST /apply")
    res = apply_license_string(body.license)

    # Best-effort device activation
    try:
        device_name = (user_agent or "device").split("(")[0].strip()[:64]
        act = await redeem_activation(body.license, device_name=device_name)
        res.update({"activation": {"ok": True, "exp": act.get("exp")}})
    except Exception as e:
        log.warning(f"[license] activation redeem failed: {e!r}")
        res.update({"activation": {"ok": False}})

    return res


@router.get("/apply")
async def apply_license_get(
    license: str = Query(..., min_length=10),
    user_agent: str | None = Header(default=None),
):
    log.info("[license] GET /apply (discouraged; use POST)")
    return await apply_license(ApplyReq(license=license), user_agent=user_agent)


@router.post("/refresh")
async def refresh(
    auth=Depends(require_auth),
    force: bool = Query(False),
    user_agent: str | None = Header(default=None),
):
    """
    Refresh the license (pull from server) and the activation.
    If activation refresh is rejected by the licensing server (401/403/404),
    delete the local activation so UI flips to 'needs activation'.
    """
    log.info(f"[license] POST /refresh force={force}")
    email = email_from_auth(auth)
    lr = await refresh_license(email, force)

    try:
        ar = await refresh_activation()
        lr.update({"activation": {"ok": True, "exp": ar.get("exp")}})
    except HTTPException as e:
        if e.status_code == 404:
            # No activation yet: seed once
            try:
                lic = current_license_string()
                if lic:
                    device_name = (user_agent or "device").split("(")[0].strip()[:64]
                    ar2 = await redeem_activation(lic, device_name=device_name)
                    lr.update({"activation": {"ok": True, "exp": ar2.get("exp")}})
                else:
                    lr.setdefault("activation", {"ok": False})
            except Exception as e2:
                log.warning(f"[license] activation redeem-on-refresh failed: {e2!r}")
                lr.setdefault("activation", {"ok": False})
        elif e.status_code in (401, 403):
            # Explicit server rejection (e.g., device_limit_reached / revoked)
            remove_activation_file()
            log.warning(f"[license] activation revoked on refresh: {e.status_code} {e.detail}")
            lr.setdefault("activation", {"ok": False, "revoked": True})
        else:
            log.warning(f"[license] activation refresh failed: {e!r}")
            lr.setdefault("activation", {"ok": False})
    except Exception as e:
        log.warning(f"[license] activation refresh unexpected error: {e!r}")
        lr.setdefault("activation", {"ok": False})

    return lr


@router.get("/status")
def status(user=Depends(require_auth)):
    email = (user.get("email") or "").strip().lower()
    st = license_status_local(expected_email=email) or {"plan": "free", "valid": False}
    act = get_activation_status()
    st["activation"] = act
    log.info(
        "[license/status] plan=%s valid=%s activation_present=%s exp=%s",
        st.get("plan"),
        st.get("valid"),
        act.get("present"),
        act.get("exp"),
    )
    return st
