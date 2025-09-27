# ext/runtime_api.py
from __future__ import annotations

import os, json, urllib.request
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import subprocess

# ✅ import from the new split modules
from .common import (
    current_os,
    read_active_runtime,
    venv_paths,
    RUNTIMES_DIR,
    VALID,
)
from .provision import (
    ensure_provisioned,
    provision_runtime,
    list_provisioned_backends,
    fetch_runtime_pack,
    wheels_dir_for_version,
    provision_runtime_versioned,
    apply_runtime_manifest,
)
from .worker import (
    start_worker,
    stop_worker,
    status,
    switch_auto,
)

router = APIRouter(prefix="/api/runtime", tags=["runtime"])

@router.get("/status")
def get_status():
    os_name = current_os()
    s = status()
    s["platform"] = os_name
    s["active"] = read_active_runtime()
    s["allowed"] = VALID.get(os_name, [])
    s["installed"] = list_provisioned_backends(os_name)  # provisioned = ready to run
    return s

@router.post("/install")
def post_install(
    backend: str = Query(..., description="cpu/cuda/vulkan (Windows); cpu/cuda/rocm/vulkan (Linux); cpu/metal (mac)"),
):
    os_name = current_os()
    try:
        out = provision_runtime(os_name, backend)
        return {"ok": True, **out}
    except FileNotFoundError as e:
        # common case: missing base wheels (fastapi/uvicorn/etc.) or backend wheels
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"install failed: {e}")

@router.post("/switch")
def post_switch(
    backend: str = Query(..., description="Target backend or 'auto'"),
    port: Optional[int] = Query(None, description="Optional fixed port; random if not set"),
):
    os_name = current_os()
    try:
        # Stop current worker first (best-effort)
        try:
            stop_worker()
        except Exception:
            pass

        if backend == "auto":
            out = switch_auto()
            return out

        # else explicit backend:
        ensure_provisioned(os_name, backend)
        out = start_worker(os_name, backend, port=port)

        # update active.json
        try:
            _, py, _ = venv_paths(os_name, backend)
            (RUNTIMES_DIR / "active.json").parent.mkdir(parents=True, exist_ok=True)
            (RUNTIMES_DIR / "active.json").write_text(
                json.dumps({"python": str(py), "backend": backend, "os": os_name}, indent=2)
            )
        except Exception:
            pass

        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"start failed: {e}")

@router.post("/stop")
def post_stop():
    return stop_worker()

@router.post("/fetch-by-url")
def post_fetch_by_url(
    backend: str = Query(..., description="cpu/cuda/…"),
    version: str = Query(..., description="e.g. v1.50.2 (folder name under wheels)"),
    url: str = Query(..., description="ZIP URL of the runtime pack"),
    sha256: str | None = Query(None, description="Optional SHA-256 of the ZIP"),
):
    os_name = current_os()
    try:
        out = fetch_runtime_pack(os_name, backend, version, url, sha256)
        root = wheels_dir_for_version(os_name, backend, version)
        has_backend = any((root / "backend").glob("*.whl"))
        has_base = any((root / "base").glob("*.whl")) if (root / "base").exists() else False
        return {"ok": True, "root": str(root), "has_base": has_base, "has_backend": has_backend, **out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch failed: {e}")

@router.post("/install-from-url")
def post_install_from_url(
    backend: str = Query(...),
    version: str = Query(...),
    url: str = Query(...),
    sha256: str | None = Query(None),
    activate: bool = Query(True),
    port: Optional[int] = Query(None),
):
    """
    One-shot convenience: download pack, provision venv from it, optionally start it.
    """
    os_name = current_os()
    try:
        # 1) fetch pack
        fetch_runtime_pack(os_name, backend, version, url, sha256)
        # 2) install into venv
        prov = provision_runtime_versioned(os_name, backend, version)
        # 3) (optional) start
        started = None
        if activate:
            try:
                stop_worker()
            except Exception:
                pass
            started = start_worker(os_name, backend, port=port)
        return {"ok": True, "provision": prov, "started": started}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"install-from-url failed: {e}")

@router.post("/install-from-cf")
def post_install_from_cf(
    backend: str = Query(..., description="cpu/cuda/rocm/vulkan/metal"),
    version: str = Query(..., description="e.g. v1.50.2"),
    activate: bool = Query(True, description="Start the runtime after install"),
    port: Optional[int] = Query(None, description="Optional fixed port"),
):
    """
    Manifest-based install:
      - Fetch /runtime/manifest from the Worker
      - Download each wheel via /runtime/wheel
      - pip install into existing backend venv
      - (optional) restart worker
    """
    os_name = current_os()
    try:
        # ensure the backend venv exists once (user installs local base first)
        vroot, _, _ = venv_paths(os_name, backend)
        if not vroot.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Backend {backend} is not provisioned. Install it once from local wheels first."
            )

        out = apply_runtime_manifest(backend, version, restart=activate)

        # if activate False but a port is provided, allow manual start on that port
        if (not activate) and port is not None:
            try:
                stop_worker()
            except Exception:
                pass
            started = start_worker(os_name, backend, port=port)
            out["started"] = started

        return out

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"install-from-cf (manifest) failed: {e}")

@router.get("/catalog")
def get_runtime_catalog():
    base = (os.getenv("LIC_SERVER_BASE") or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="LIC_SERVER_BASE not set")
    url = f"{base}/runtime/catalog"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = r.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"catalog fetch failed: {e}")

@router.post("/apply-delta")
def post_apply_delta(
    backend: str = Query(...),
    version: str = Query(..., description="target version to apply (manifest-based)"),
    restart: bool = Query(True)
):
    try:
        return apply_runtime_manifest(backend, version, restart=restart)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delta apply failed: {e}")

@router.post("/install-wheels")
def post_install_wheels(
    backend: str = Query(...),
    wheel_urls: list[str] = Query(..., description="one or more direct .whl URLs"),
    no_deps: bool = Query(True), force: bool = Query(True), restart: bool = Query(True),
):
    """Dev helper: install one or more wheels into existing venv."""
    try:
        os_name = current_os()
        vroot, py, pip = venv_paths(os_name, backend)
        if not Path(vroot).exists():
            raise RuntimeError("venv missing; install the backend once first")
        for url in wheel_urls:
            subprocess.run(
                [str(pip), "install", "--force-reinstall"] + (["--no-deps"] if no_deps else []) + [url],
                check=True
            )
        if restart:
            try:
                stop_worker()
            except Exception:
                pass
            start_worker(os_name, backend)
        return {"ok": True, "backend": backend, "count": len(wheel_urls)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"install-wheels failed: {e}")
    
@router.get("/logs")
def get_runtime_logs(limit: int = Query(2000, ge=100, le=20000)):
    from .worker import worker_log_tail, status as wstatus
    return {
        "status": wstatus(),
        "tail": worker_log_tail(limit)
    }

@router.get("/worker-log-tail")
def get_worker_log_tail(n: int = 4000):
    """Return the last N bytes of the runtime worker's stdout/stderr."""
    try:
        from .worker import worker_log_tail
        tail = worker_log_tail(max_bytes=max(200, min(n, 200_000)))
        # FastAPI will JSON-escape by default; return as plain text:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(tail or "(no worker output yet)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to read worker log tail: {e}")