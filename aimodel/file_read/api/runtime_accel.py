from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from ..services.accel_prefs import read_pref, write_pref, AccelPref, detect_backends

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

class AccelBody(BaseModel):
    accel: str
    n_gpu_layers: int | None = None

    @field_validator("accel")
    @classmethod
    def _v_accel(cls, v: str) -> str:
        v = (v or "").lower()
        if v not in {"auto", "cpu", "cuda", "metal", "rocm"}:
            raise ValueError("accel must be one of: auto,cpu,cuda,metal,rocm")
        return v

@router.get("/accel")
def get_accel():
    pref = read_pref()
    return {
        "pref": {"accel": pref.accel, "n_gpu_layers": pref.n_gpu_layers},
        "detected": detect_backends(),
        "note": "Preference applies to NEW model loads only.",
    }

@router.post("/accel")
def set_accel(body: AccelBody):
    pref = AccelPref(accel=body.accel, n_gpu_layers=body.n_gpu_layers)
    write_pref(pref)
    return {"ok": True, "pref": {"accel": pref.accel, "n_gpu_layers": pref.n_gpu_layers}}
