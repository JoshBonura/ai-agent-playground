# ext/runtime_api.py
from fastapi import APIRouter, HTTPException, Query
from enum import Enum
from typing import Literal, Optional

from .runtime_manager import current_os, install_runtime, start_worker, stop_worker, status, mapping

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

# Dynamic enum factory so docs show the right allowed values per-OS
def backend_choices_for(os_name: str) -> list[str]:
    from .runtime_manager import VALID
    return VALID[os_name]

class PortRange(int):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    @classmethod
    def validate(cls, v):
        v = int(v)
        if not (1024 <= v <= 65535):
            raise ValueError("port must be 1024–65535")
        return v

@router.get("/status")
def get_status():
    s = status()
    s["platform"] = current_os()
    return s

@router.post("/install")
def post_install(
    backend: str = Query(..., description="cpu/cuda/vulkan on Windows; cpu/cuda/rocm/vulkan on Linux; cpu/metal on macOS")
):
    os_name = current_os()
    # Validate against OS-specific set
    try:
        mapping(os_name, backend)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = install_runtime(os_name, backend)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"install failed: {e}")

@router.post("/switch")
def post_switch(
    backend: str = Query(..., description="Target backend for this OS"),
    port: PortRange = 52111
):
    os_name = current_os()
    try:
        mapping(os_name, backend)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # stop current (ignore if none)
    stop_worker()

    # ensure installed (idempotent)
    try:
        install_runtime(os_name, backend)
    except Exception:
        # It's okay if already installed; we proceed to start
        pass

    try:
        # start_worker should include a health wait; if not, add it there
        return start_worker(os_name, backend, port=int(port))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"start failed: {e}")

@router.post("/verify")
def post_verify(backend: str):
    os_name = current_os()
    try:
        req, wheels = mapping(os_name, backend)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not wheels.exists() or not req.exists():
        raise HTTPException(400, f"missing: {wheels} or {req}")
    # pip download to a temp dir (offline) ensures all wheels are present
    import tempfile, subprocess, shutil
    tmp = tempfile.mkdtemp()
    try:
        cmd = ["python","-m","pip","download","--no-index","--find-links",str(wheels), "-r", str(req), "-d", tmp]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise HTTPException(500, f"verify failed:\n{p.stdout}\n{p.stderr}")
        return {"ok": True}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)