# ext/common.py
from __future__ import annotations

import hashlib
import json
import os
import platform as py_platform
import platform
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from aimodel.core.settings import SETTINGS

# ----------------------------
# App data and paths
# ----------------------------
def app_data_dir() -> Path:
    """
    Returns the root folder where LocalMind stores user data.
    Priority:
      1) LOCALMIND_DATA_DIR (set by Electron main.ts to app.getPath('userData'))
      2) LOCALAI_HOME (legacy override)
      3) OS defaults
    """
    lm = os.getenv("LOCALMIND_DATA_DIR")
    if lm:
        return Path(lm)

    override = os.getenv("LOCALAI_HOME")
    if override:
        return Path(override)

    s = py_platform.system().lower()
    if s.startswith("win"):
        base = Path(os.getenv("APPDATA") or Path.home())
        return base / "LocalAI"
    if s.startswith("darwin"):
        return Path.home() / "Library" / "Application Support" / "LocalAI"
    # linux + other
    xdg = os.getenv("XDG_DATA_HOME")
    return Path(xdg if xdg else (Path.home() / ".local" / "share")) / "LocalAI"

# Store venvs/active manifest under the app data dir
RUNTIMES_DIR = app_data_dir() / ".runtime" / "venvs"
ACTIVE_JSON = RUNTIMES_DIR / "active.json"

# Inputs for offline installs (overridable via env from Electron)
REQ_ROOT = Path(os.getenv("LM_REQUIREMENTS_ROOT") or Path("ext") / "requirements")
WHEELS_ROOT = Path(os.getenv("LM_WHEELS_ROOT") or Path("ext") / "wheels")

OS_DIR = {"windows": "win", "linux": "linux", "mac": "mac"}

VALID = {
    "windows": ["cpu", "cuda", "vulkan"],
    "linux":   ["cpu", "cuda", "rocm", "vulkan"],
    "mac":     ["cpu", "metal"],
}

STAMP_NAME = ".runtime.json"  # marks a backend as provisioned (venv ready)

# ----------------------------
# Small HTTP helpers
# ----------------------------
def _http_get(url: str, *, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"localai-runtime-installer/{sys.version_info.major}.{sys.version_info.minor}",
            "Accept": "*/*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if os.getenv("LOG_RUNTIME_DEBUG"):
                print(f"[runtime:http] {url} -> {getattr(r, 'status', 'ok')} {len(data)}B")
            return data
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        preview = body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} on GET {url} :: {preview}") from e
    except Exception as e:
        raise RuntimeError(f"HTTP error on GET {url}: {e!s}") from e

def _get_json(url: str) -> dict:
    raw = _http_get(url)
    # Handle UTF-8 BOM if present
    txt = raw.decode("utf-8-sig", errors="strict")
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        preview = txt[:200]
        raise RuntimeError(f"JSON decode failed from {url}: {e.msg} at pos {e.pos}; preview={preview!r}") from e

def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

# ----------------------------
# OS helpers
# ----------------------------
def current_os() -> str:
    s = py_platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s.startswith("linux"):
        return "linux"
    if s.startswith("darwin"):
        return "mac"
    raise RuntimeError(f"Unsupported OS: {s}")

def mapping(os_name: str, backend: str) -> tuple[Path, Path]:
    if os_name not in VALID:
        raise ValueError(f"Unsupported OS {os_name}")
    if backend not in VALID[os_name]:
        raise ValueError(f"{backend} not valid for {os_name}")
    req = REQ_ROOT / f"{os_name}.{backend}.txt"
    wheels = WHEELS_ROOT / OS_DIR[os_name] / backend
    return req, wheels

def base_mapping(os_name: str) -> tuple[Path, Path]:
    """Optional base layer (fastapi/uvicorn/etc.)."""
    req = REQ_ROOT / "base.txt"
    wheels = WHEELS_ROOT / OS_DIR[os_name] / "base"
    return req, wheels

def venv_paths(os_name: str, backend: str) -> tuple[Path, Path, Path]:
    vroot = RUNTIMES_DIR / os_name / backend / ".venv"
    if current_os() == "windows":
        py = vroot / "Scripts" / "python.exe"
        pip = vroot / "Scripts" / "pip.exe"
    else:
        py = vroot / "bin" / "python"
        pip = vroot / "bin" / "pip"
    return vroot, py, pip

def read_active_runtime() -> dict | None:
    try:
        if ACTIVE_JSON.exists():
            return json.loads(ACTIVE_JSON.read_text())
    except Exception:
        pass
    return None

# ----------------------------
# Cloudflare URL helpers
# ----------------------------
def _py_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"

def _arch_token() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return m or "x86_64"

def _os_token() -> str:
    s = current_os()
    return {"windows": "win", "linux": "linux", "mac": "mac"}[s]

def build_cf_manifest_url(backend: str, version: str) -> str:
    base = (os.getenv("LIC_SERVER_BASE") or "").rstrip("/")
    if not base:
        raise RuntimeError("LIC_SERVER_BASE not set")
    os_tok = _os_token()
    return f"{base}/runtime/manifest?os={os_tok}&backend={backend}&version={urllib.parse.quote(version)}"

def build_cf_wheel_url(key: str) -> str:
    from urllib.parse import quote
    base = (os.getenv("LIC_SERVER_BASE") or "").rstrip("/")
    if not base:
        raise RuntimeError("LIC_SERVER_BASE not set")
    # keep '/' unencoded; encode only what’s necessary
    encoded = quote(key, safe="/-_.~")
    return f"{base}/runtime/wheel?key={encoded}"

def build_cf_pack_url(backend: str, version: str) -> str:
    base = os.getenv("LIC_SERVER_BASE", "").rstrip("/")
    if not base:
        raise RuntimeError("LIC_SERVER_BASE is not set; point it to your Worker base URL.")
    os_tok = _os_token()
    arch = _arch_token()
    py = _py_tag()
    return f"{base}/runtime/pack?backend={backend}&os={os_tok}&arch={arch}&py={py}&version={urllib.parse.quote(version)}"

# re-export settings for detection logic
__all__ = [
    "SETTINGS",
    "RUNTIMES_DIR", "ACTIVE_JSON",
    "REQ_ROOT", "WHEELS_ROOT", "OS_DIR", "VALID", "STAMP_NAME",
    "_http_get", "_get_json", "_sha256_bytes",
    "current_os", "mapping", "base_mapping", "venv_paths", "read_active_runtime",
    "build_cf_manifest_url", "build_cf_wheel_url", "build_cf_pack_url",
]
