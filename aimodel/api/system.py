from __future__ import annotations

from fastapi import APIRouter
from ..core.logging import get_logger
from ..services.system_snapshot import get_system_snapshot
from fastapi import APIRouter, HTTPException
from ..rag.ingest.ocr import _ensure_tesseract_available, _install_hint, MissingTesseractError

router = APIRouter(prefix="/api/system", tags=["system"])
log = get_logger(__name__)

@router.get("/resources")
async def system_resources():
    # Instant return of the last cached snapshot (updated by poller)
    return await get_system_snapshot()

# Optional quick debug endpoint to see NVML status
@router.get("/nvml-debug")
def nvml_debug():
    import os, ctypes, platform, json
    info = {
        "platform": platform.platform(),
        "env_NVML_DLL_PATH": os.getenv("NVML_DLL_PATH"),
        "env_NVML_DLL": os.getenv("NVML_DLL"),
        "preload_ok": False,
        "preload_error": None,
        "pynvml_init_ok": False,
        "pynvml_error": None,
        "driver_version": None,
    }

    path = info["env_NVML_DLL_PATH"] or info["env_NVML_DLL"]
    if path:
        try:
            ctypes.WinDLL(path)
            info["preload_ok"] = True
        except OSError as e:
            info["preload_error"] = str(e)

    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        info["pynvml_init_ok"] = True
        try:
            info["driver_version"] = pynvml.nvmlSystemGetDriverVersion().decode("utf-8", "ignore")
        except Exception:
            pass
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
    except Exception as e:
        info["pynvml_error"] = str(e)

    return json.loads(json.dumps(info, default=str))

@router.get("/ocr-check")
def ocr_check():
    try:
        _ensure_tesseract_available()
        return {"ok": True, "installed": True}
    except MissingTesseractError as e:
        hint = _install_hint()
        raise HTTPException(
            status_code=424,
            detail={
                "code": "TESSERACT_MISSING",
                "message": str(e),
                "installUrl": hint["url"],
                "note": hint["note"],
            },
        )

