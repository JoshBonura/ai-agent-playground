from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel

from ..deps.auth_deps import require_auth
# NEW: device activation helpers
from ..services.licensing_service import \
    get_activation_status  # <- tiny helper to read local activation.json
from ..services.licensing_service import \
    redeem_activation  # <- we'll add in service file below
from ..services.licensing_service import \
    refresh_activation  # <- we'll add in service file below
from ..services.licensing_service import (apply_license_string,
                                          email_from_auth,
                                          license_status_local,
                                          refresh_license)

router = APIRouter(prefix="/api/license", tags=["license"])


class ApplyReq(BaseModel):
    license: str


@router.post("/apply")
async def apply_license(body: ApplyReq, user_agent: str | None = Header(default=None)):
    """
    1) Verify and persist the LM1 license locally.
    2) Redeem a device-scoped activation token (best-effort: do not fail apply if server unreachable).
    """
    log.info("[license] POST /apply")
    res = apply_license_string(body.license)

    # Best-effort device activation
    try:
        device_name = (user_agent or "device").split("(")[0].strip()[:64]
        act = await redeem_activation(body.license, device_name=device_name)
        res.update({"activation": {"ok": True, "exp": act.get("exp")}})
    except Exception as e:
        # Do not block license apply on activation network issues
        log.warning(f"[license] activation redeem failed: {e!r}")
        res.update({"activation": {"ok": False}})

    return res


@router.get("/apply")
async def apply_license_get(
    license: str = Query(..., min_length=10), user_agent: str | None = Header(default=None)
):
    log.info("[license] GET /apply (discouraged; use POST)")
    return await apply_license(ApplyReq(license=license), user_agent=user_agent)


@router.post("/refresh")
async def refresh(auth=Depends(require_auth), force: bool = Query(False)):
    """
    Refresh:
    - License (if expiring soon or forced)
    - Device activation token (rolling 30d window), best-effort
    """
    log.info(f"[license] POST /refresh force={force}")
    email = email_from_auth(auth)
    lr = await refresh_license(email, force)

    # Best-effort activation refresh
    try:
        ar = await refresh_activation()
        lr.update({"activation": {"ok": True, "exp": ar.get("exp")}})
    except Exception as e:
        log.warning(f"[license] activation refresh failed: {e!r}")
        # Keep license refresh result even if activation refresh fails
        if "activation" not in lr:
            lr["activation"] = {"ok": False}

    return lr


@router.get("/status")
def status(user=Depends(require_auth)):
    email = (user.get("email") or "").strip().lower()
    st = license_status_local(expected_email=email) or {"plan": "free", "valid": False}
    # add activation local view (no network)
    st["activation"] = get_activation_status()
    return st
