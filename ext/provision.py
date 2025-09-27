# ext/runtime/provision.py
from __future__ import annotations

import sys
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

from .common import (
    ACTIVE_JSON,
    STAMP_NAME,
    VALID,
    base_mapping,
    build_cf_manifest_url,
    build_cf_wheel_url,
    current_os,
    mapping,
    venv_paths,
    _get_json,
    _http_get,
    _sha256_bytes,
)

LOG_DEBUG = bool(os.getenv("LOG_RUNTIME_DEBUG"))

def _log(msg: str):
    if LOG_DEBUG:
        print(msg, flush=True)

# ----------------------------
# Provisioning helpers
# ----------------------------
def _stamp_path(os_name: str, backend: str) -> Path:
    vroot, _, _ = venv_paths(os_name, backend)
    return vroot.parent / STAMP_NAME

def is_provisioned(os_name: str, backend: str) -> bool:
    ok = _stamp_path(os_name, backend).exists()
    _log(f"[runtime:provision] is_provisioned os={os_name} backend={backend} -> {ok}")
    return ok

def list_provisioned_backends(os_name: str) -> list[str]:
    listed = [b for b in VALID.get(os_name, []) if is_provisioned(os_name, b)]
    _log(f"[runtime:provision] list_provisioned_backends({os_name}) -> {listed}")
    return listed

def ensure_venv(os_name: str, backend: str, python_exe: str | None = None) -> tuple[Path, Path, Path]:
    vroot, py, pip = venv_paths(os_name, backend)
    if not vroot.exists():
        _log(f"[runtime:provision] creating venv at {vroot}")
        vroot.parent.mkdir(parents=True, exist_ok=True)
        base_py = python_exe or sys.executable
        subprocess.run([base_py, "-m", "venv", str(vroot)], check=True)
    else:
        _log(f"[runtime:provision] reusing existing venv at {vroot}")
    return vroot, py, pip

def _run_pip(cmd: list[str], stream: bool = False):
    """
    Run pip with optional streaming (when LOG_RUNTIME_DEBUG=1).
    Returns (stdout, stderr) strings (may be empty if stream=True).
    """
    if LOG_DEBUG:
        pretty = " ".join(cmd)
        print(f"[runtime:pip] {pretty}", flush=True)
    if stream or LOG_DEBUG:
        # stream to current stdout/stderr so you see progress live
        proc = subprocess.run(cmd, check=True)
        return "", ""
    else:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return proc.stdout or "", proc.stderr or ""

def _normalize_wheel_dirs(wheels: Path | Iterable[Path]) -> list[Path]:
    wheel_dirs = [wheels] if isinstance(wheels, Path) else list(wheels)
    wheel_dirs = [Path(p) for p in wheel_dirs]
    # Keep only existing dirs that contain at least one .whl
    good = [p for p in wheel_dirs if p.exists() and any(p.glob("*.whl"))]
    return good

def _offline_install(pip: Path, req: Path, wheels: Path | Iterable[Path]):
    """
    Install packages strictly from local wheels directories using a requirements file.
    Supports one or many --find-links directories.
    """
    if not req.exists():
        raise FileNotFoundError(f"Requirements file missing: {req}")

    wheel_dirs = _normalize_wheel_dirs(wheels)
    if not wheel_dirs:
        raise FileNotFoundError("No wheel directories found (missing/empty).")

    # Enforce offline behavior and avoid sdists
    env = os.environ.copy()
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_ONLY_BINARY"] = ":all:"

    cmd = [str(pip), "install", "--no-index"]
    for d in wheel_dirs:
        cmd += ["--find-links", str(d)]
    cmd += ["-r", str(req)]

    try:
        if LOG_DEBUG:
            print(f"[runtime:offline] req={req} wheels={[str(d) for d in wheel_dirs]}")
            print(f"[runtime:pip] {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True, capture_output=not LOG_DEBUG, text=True, env=env)
    except subprocess.CalledProcessError as e:
        out = (e.stdout or "")[-4000:] if hasattr(e, "stdout") else ""
        err = (e.stderr or "")[-4000:] if hasattr(e, "stderr") else ""
        raise RuntimeError(
            f"pip failed during offline install :: exit={e.returncode}\n"
            f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
        )

def provision_runtime(os_name: str, backend: str, python_exe: str | None = None) -> dict:
    """One-time venv creation + offline install of base + backend. Idempotent."""
    _log(f"[runtime:provision] start os={os_name} backend={backend}")
    req_backend, wheels_backend = mapping(os_name, backend)
    vroot, py, pip = ensure_venv(os_name, backend, python_exe)

    # pip upgrade (best-effort)
    try:
        _run_pip([str(py), "-m", "pip", "install", "--upgrade", "pip"], stream=False)
    except subprocess.CalledProcessError:
        _log("[runtime:provision] pip upgrade failed (ignored)")

    # Optional base layer first
    req_base, wheels_base = base_mapping(os_name)
    if req_base.exists() and wheels_base.exists() and any(wheels_base.glob("*.whl")):
        _offline_install(pip, req_base, wheels_base)
    else:
        _log("[runtime:provision] no base layer found")

    # Backend layer — search backend dir AND base dir so deps in base are resolved
    # (e.g., diskcache needed by llama-cpp-python)
    wheel_search = [wheels_backend, wheels_base]
    _offline_install(pip, req_backend, wheel_search)

    # write stamp
    stamp = {
        "platform": os_name,
        "backend": backend,
        "python": str(py),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _stamp_path(os_name, backend).write_text(json.dumps(stamp, indent=2))

    # active.json (best-effort)
    ACTIVE_JSON.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_JSON.write_text(json.dumps(stamp, indent=2))
    _log(f"[runtime:provision] complete backend={backend} venv={vroot}")
    return {"ok": True, "venv": str(vroot), "manifest": stamp}

def ensure_provisioned(os_name: str, backend: str):
    if not is_provisioned(os_name, backend):
        provision_runtime(os_name, backend)

def warm_provision_all_possible():
    os_name = current_os()
    for b in VALID.get(os_name, []):
        if is_provisioned(os_name, b):
            continue
        try:
            req, wheels = mapping(os_name, b)
            if req.exists() and wheels.exists() and any(wheels.glob("*.whl")):
                _log(f"[runtime:warm] provisioning {b}")
                ensure_provisioned(os_name, b)
        except Exception as e:
            _log(f"[runtime:warm] skipped {b}: {e}")

# ----------------------------
# Versioned pack fetch & install (ZIP packs)
# ----------------------------
def _download_to(path: Path, url: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as r:
        data = r.read()
    path.write_bytes(data)
    return path

def _unzip_bytes_to_dir(data: bytes, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dest)

def wheels_dir_for_version(os_name: str, backend: str, version: str) -> Path:
    from .common import WHEELS_ROOT, OS_DIR
    return WHEELS_ROOT / OS_DIR[os_name] / backend / version

def _base_dir_for_pack(os_name: str, backend: str, version: str) -> Path:
    return wheels_dir_for_version(os_name, backend, version) / "base"

def _backend_dir_for_pack(os_name: str, backend: str, version: str) -> Path:
    return wheels_dir_for_version(os_name, backend, version) / "backend"

def fetch_runtime_pack(os_name: str, backend: str, version: str, url: str, sha256: str | None = None) -> dict:
    if backend not in VALID.get(os_name, []):
        raise ValueError(f"{backend} not valid for {os_name}")

    dest_root = wheels_dir_for_version(os_name, backend, version)
    dest_root.mkdir(parents=True, exist_ok=True)

    _log(f"[runtime:pack] GET {url}")
    with urllib.request.urlopen(url) as r:
        blob = r.read()
    _log(f"[runtime:pack] {len(blob)} bytes")

    if sha256:
        import hashlib
        got = hashlib.sha256(blob).hexdigest()
        if got.lower() != sha256.lower():
            raise RuntimeError(f"SHA256 mismatch for pack {version}: expected {sha256}, got {got}")

    _unzip_bytes_to_dir(blob, dest_root)

    if not any((_backend_dir_for_pack(os_name, backend, version)).glob("*.whl")):
        raise RuntimeError("Downloaded pack missing backend wheels (backend/*.whl)")

    _log(f"[runtime:pack] unpacked to {dest_root}")
    return {"ok": True, "root": str(dest_root)}

def provision_runtime_versioned(os_name: str, backend: str, version: str, python_exe: str | None = None) -> dict:
    vroot, py, pip = ensure_venv(os_name, backend, python_exe)

    try:
        _run_pip([str(py), "-m", "pip", "install", "--upgrade", "pip"], stream=False)
    except subprocess.CalledProcessError:
        _log("[runtime:versioned] pip upgrade failed (ignored)")

    req_base, _ = base_mapping(os_name)
    req_backend, _ = mapping(os_name, backend)

    base_wheels_dir = _base_dir_for_pack(os_name, backend, version)
    be_wheels_dir   = _backend_dir_for_pack(os_name, backend, version)

    # Base from pack (if present)
    if req_base.exists() and base_wheels_dir.exists() and any(base_wheels_dir.glob("*.whl")):
        _offline_install(pip, req_base, base_wheels_dir)
    else:
        _log("[runtime:versioned] no base wheels in pack")

    # Backend from pack, but also search base dir to satisfy shared deps
    if not (be_wheels_dir.exists() and any(be_wheels_dir.glob("*.whl"))):
        raise FileNotFoundError(f"No backend wheels found at {be_wheels_dir}")
    _offline_install(pip, req_backend, [be_wheels_dir, base_wheels_dir])

    stamp = {
        "platform": os_name,
        "backend": backend,
        "python": str(py),
        "version": version,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _stamp_path(os_name, backend).write_text(json.dumps(stamp, indent=2))
    ACTIVE_JSON.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_JSON.write_text(json.dumps(stamp, indent=2))
    _log(f"[runtime:versioned] complete backend={backend} version={version} venv={vroot}")
    return {"ok": True, "venv": str(vroot), "manifest": stamp}

# ----------------------------
# Incremental wheel install (from CF manifest)
# ----------------------------
def install_wheels_into_backend(
    backend: str,
    wheels: list[dict],
    *,
    no_deps: bool = True,
    force: bool = True
) -> dict:
    """
    Install a list of wheels (from CF worker) into an existing backend venv.

    Each item in `wheels` should be:
      { "path": "wheels/win/cpu/v1.50.2/numpy-1.26.4-cp311-cp311-win_amd64.whl", "sha256": "<optional hex>" }

    Behavior:
      - strictly offline (PIP_NO_INDEX=1), no resolver; won't hit PyPI
      - installs exactly the wheels you provide, in a stable order
      - verifies sha256 if present
      - cleans temp files
    """
    os_name = current_os()
    vroot, _py, pip = venv_paths(os_name, backend)
    if not vroot.exists():
        raise RuntimeError(f"Backend {backend} venv not found; install it once first.")

    # prefer numpy first, typing_extensions next, llama last
    def _prio(path: str) -> int:
        name = path.rsplit("/", 1)[-1].lower()
        if name.startswith("numpy-"): return 0
        if name.startswith("typing_extensions-"): return 1
        if name.startswith(("llama_cpp_python-", "llama-cpp-python-")): return 9
        return 5

    # basic schema sanity
    if not isinstance(wheels, list) or not all(isinstance(x, dict) and "path" in x for x in wheels):
        raise RuntimeError("Bad wheels schema: expected a list of {'path': ..., 'sha256'?: ...}")

    wheels_sorted = sorted(wheels, key=lambda w: _prio(w["path"]))
    tmp_dirs: list[str] = []
    installed: list[str] = []

    if LOG_DEBUG:
        print(f"[runtime:manifest] installing {len(wheels_sorted)} wheel(s) into {backend} venv", flush=True)

    try:
        for w in wheels_sorted:
            wheel_key = w["path"]
            wheel_name = wheel_key.split("/")[-1]
            want_hash = (w.get("sha256") or "").lower()

            # fetch
            url = build_cf_wheel_url(wheel_key)
            if LOG_DEBUG:
                print(f"[runtime:wheel] GET {url} (key={wheel_key})", flush=True)
            blob = _http_get(url)

            # sha256 check (if provided)
            got_hash = _sha256_bytes(blob)
            if want_hash and got_hash != want_hash:
                raise RuntimeError(f"sha256 mismatch for {wheel_key}: expected={want_hash} got={got_hash}")

            # write to temp with REAL filename so pip recognizes tags
            tmp_dir = tempfile.mkdtemp(prefix="rt_wheels_")
            tmp_dirs.append(tmp_dir)
            tmp_path = os.path.join(tmp_dir, wheel_name)
            with open(tmp_path, "wb") as f:
                f.write(blob)
            if LOG_DEBUG:
                print(f"[runtime:wheel] wrote {tmp_path} ({len(blob)} bytes)", flush=True)

            # build pip cmd — strictly offline
            cmd = [str(pip), "install"]
            if no_deps:
                cmd += ["--no-deps"]
            if force:
                cmd += ["--force-reinstall"]
            if LOG_DEBUG:
                cmd += ["-vv"]
            cmd += [tmp_path]

            env = os.environ.copy()
            env["PIP_NO_INDEX"] = "1"
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            env["PIP_ONLY_BINARY"] = ":all:"

            if LOG_DEBUG:
                print(f"[runtime:wheel] pip cmd: {' '.join(cmd)}", flush=True)

            try:
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=not LOG_DEBUG,  # stream in debug, capture otherwise
                    text=True,
                    env=env,
                )
            except subprocess.CalledProcessError as e:
                out = (e.stdout or "")[-4000:]
                err = (e.stderr or "")[-4000:]
                raise RuntimeError(
                    f"pip failed installing {wheel_key} :: exit={e.returncode}\n"
                    f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
                )

            installed.append(wheel_key)
            if LOG_DEBUG:
                print(f"[runtime:wheel] installed {wheel_name}", flush=True)

    finally:
        # tidy up temp dirs
        for d in tmp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    return {"ok": True, "backend": backend, "installed": installed, "venv": str(vroot)}

def apply_runtime_manifest(backend: str, version: str, *, restart: bool = True) -> dict:
    manifest_url = build_cf_manifest_url(backend, version)
    _log(f"[runtime:manifest] GET {manifest_url}")
    data = _get_json(manifest_url)

    wheels = data.get("wheels") or []
    if not isinstance(wheels, list) or not all(isinstance(x, dict) and "path" in x for x in wheels):
        raise RuntimeError(f"Bad manifest schema from {manifest_url}")

    _log(f"[runtime:manifest] {len(wheels)} wheel(s) found")
    out = install_wheels_into_backend(backend, wheels)

    # update stamp
    stamp_path = _stamp_path(current_os(), backend)
    meta = {}
    if stamp_path.exists():
        try:
            meta = json.loads(stamp_path.read_text())
        except Exception:
            meta = {}
    meta.update({"version": version})
    stamp_path.write_text(json.dumps(meta, indent=2))
    _log(f"[runtime:manifest] stamped version={version} at {stamp_path}")

    if restart:
        from .worker import stop_worker, start_worker, worker_log_tail
        try:
            _log("[runtime:manifest] restarting worker")
            stop_worker()
            start_worker(current_os(), backend)
        except Exception as e:
            # Surface the worker tail right in the error — this will show up in the 500 detail
            tail = worker_log_tail(2000)
            raise RuntimeError(f"restart failed: {e}\n--- worker log tail ---\n{tail}")

    return {"ok": True, "applied": version, **out}
