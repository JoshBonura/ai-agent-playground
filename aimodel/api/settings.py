from typing import Any

from fastapi import APIRouter, Body, Query

from ..core.logging import get_logger
from ..core.settings import SETTINGS

log = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

def _redact(d: dict) -> dict:
    """Basic redaction of likely secret keys."""
    import json
    def scrub(k, v):
        key = str(k).lower()
        if any(x in key for x in ["key", "token", "secret", "password"]):
            return "<redacted>"
        return v
    out = {}
    for k, v in (d or {}).items():
        try:
            json.dumps(v)
            out[k] = scrub(k, v)
        except Exception:
            out[k] = repr(v)
    return out

@router.get("/settings/inspect")
async def settings_inspect(session_id: str | None = None):
    """Debug-only: see what the backend thinks your settings are."""
    defaults  = SETTINGS.defaults
    overrides = SETTINGS.overrides
    effective = SETTINGS.effective(session_id=session_id)

    log.info(
        "[settings.inspect] session_id=%s defaults_keys=%s overrides_keys=%s",
        session_id, list(defaults.keys()), list(overrides.keys())
    )
    # show a few high-signal fields in logs:
    wd = (effective.get("worker_default") or {})
    log.info(
        "[settings.inspect] worker_default: accel=%r device=%r n_gpu_layers=%r n_threads=%r n_ctx=%r kv_offload=%r limit_offload_to_dedicated_vram=%r",
        wd.get("accel"), wd.get("device"), wd.get("n_gpu_layers"),
        wd.get("n_threads"), wd.get("n_ctx"),
        wd.get("offload_kv_to_gpu"), wd.get("limit_offload_to_dedicated_vram"),
    )
    # return redacted copies to client
    return {
        "defaults": _redact(defaults),
        "overrides": _redact(overrides),
        "effective": _redact(effective),
    }

@router.get("/defaults")
def get_defaults():
    return SETTINGS.defaults


@router.get("/overrides")
def get_overrides():
    return SETTINGS.overrides



@router.patch("/overrides")
def patch_overrides(payload: dict[str, Any] = Body(...)):
    SETTINGS.patch_overrides(payload)
    return {"ok": True, "overrides": SETTINGS.overrides}


@router.put("/overrides")
def put_overrides(payload: dict[str, Any] = Body(...)):
    SETTINGS.replace_overrides(payload)
    return {"ok": True, "overrides": SETTINGS.overrides}



@router.get("/effective")
def get_effective(session_id: str | None = Query(default=None, alias="sessionId")):
    return SETTINGS.effective(session_id=session_id)
