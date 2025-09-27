from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps.admin_deps import require_admin
from ..deps.license_deps import require_personal_pro
from ..services.licensing_service import _lic_base, _lic_get_json, _lic_post_json, current_license_string
from ..services.licensing_service import redeem_activation, current_device_info, device_id
from ..core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/devices", tags=["devices"])


def _require_license() -> str:
    lic = (current_license_string() or "").strip()
    if not lic:
        raise HTTPException(404, "license_not_present")
    return lic


@router.get("")
async def list_devices(_=Depends(require_admin)):
    base = _lic_base()
    lic = _require_license()
    data = await _lic_get_json(f"{base}/api/devices", params={"license": lic}) or []
    cur = device_id()
    for d in data:
        d["isCurrent"] = (d.get("id") == cur)
    return [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "platform": d.get("platform"),
            "appVersion": d.get("appVersion"),
            "lastSeen": d.get("lastSeen"),
            "isCurrent": bool(d.get("isCurrent")),
            "exp": d.get("exp"),
        }
        for d in data
    ]


@router.get("/current")
async def current_device(_=Depends(require_admin)):
    """
    Return local device info and whether the licensing server currently lists it.
    """
    info = current_device_info()
    res = {"local": info, "onServer": False, "serverRecord": None}

    try:
        base = _lic_base()
        lic = _require_license()
        arr = await _lic_get_json(f"{base}/api/devices", params={"license": lic}) or []
        for d in arr:
            if d.get("id") == info["id"]:
                res["onServer"] = True
                res["serverRecord"] = d
                break
    except Exception as e:
        log.warning(f"[devices/current] server lookup failed: {e!r}")

    return res


@router.post("/rename")
async def rename_device(body: dict, _=Depends(require_admin)):
    name = (body or {}).get("name")
    device_id_val = (body or {}).get("deviceId")
    lic = _require_license()
    if not device_id_val:
        raise HTTPException(400, "missing_fields")
    await _lic_post_json(
        f"{_lic_base()}/api/devices/rename",
        body={"license": lic, "deviceId": device_id_val, "name": name},
    )
    return {"ok": True}


@router.delete("/{device_id_val}")
async def revoke_device(device_id_val: str, _=Depends(require_admin)):
    lic = _require_license()
    await _lic_post_json(
        f"{_lic_base()}/api/devices/revoke",
        body={"license": lic, "deviceId": device_id_val},
    )
    return {"ok": True}


@router.post("/activate-here")
async def activate_here(
    _admin=Depends(require_admin),
    _pro=Depends(require_personal_pro),
):
    """
    Admin convenience to activate THIS device.
    Requires: admin AND the caller personally has Pro.
    """
    lic = _require_license()
    res = await redeem_activation(lic, device_name="this device")
    return {"ok": True, "exp": res.get("exp")}
