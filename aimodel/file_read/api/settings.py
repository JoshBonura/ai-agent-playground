from typing import Any

from fastapi import APIRouter, Body, Query

from ..core.logging import get_logger
from ..core.settings import SETTINGS

log = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


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


@router.get("/adaptive")
def get_adaptive(session_id: str | None = Query(default=None, alias="sessionId")):
    return SETTINGS.adaptive(session_id=session_id)


@router.post("/adaptive/recompute")
def recompute_adaptive(session_id: str | None = Query(default=None, alias="sessionId")):
    SETTINGS.recompute_adaptive(session_id=session_id)
    return {"ok": True, "adaptive": SETTINGS.adaptive(session_id=session_id)}


@router.get("/effective")
def get_effective(session_id: str | None = Query(default=None, alias="sessionId")):
    return SETTINGS.effective(session_id=session_id)
