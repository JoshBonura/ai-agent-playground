# ext/worker.py
from __future__ import annotations

import ctypes
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from ctypes.util import find_library
from pathlib import Path
from typing import Optional
from collections import deque
from threading import Thread, Lock

from .common import (
    ACTIVE_JSON,
    SETTINGS,
    VALID,
    current_os,
    venv_paths,
)
from .provision import (
    ensure_provisioned,
    list_provisioned_backends,
)

# ----------------------------
# Worker launch/stop + logging
# ----------------------------
_worker_proc: Optional[subprocess.Popen] = None
_worker_info: Optional[dict] = None

# keep an in-memory log tail so we can return it on errors / via API
_LOG_TAIL_MAX = int(os.getenv("LM_WORKER_LOG_TAIL_BYTES", "100000"))  # ~100 KB by default
_LOG_TAIL = deque()            # type: ignore[var-annotated]  # list[str] chunks
_LOG_LOCK = Lock()
_LOG_FILE_PATH = os.getenv("LM_WORKER_LOG_FILE", "").strip()  # optional tee to file

def _log_tail_append(s: str):
    # maintain a rough byte budget; we store by lines/chunks for simplicity
    with _LOG_LOCK:
        _LOG_TAIL.append(s)
        # trim if we exceed budget
        total = sum(len(x) for x in _LOG_TAIL)
        while total > _LOG_TAIL_MAX and _LOG_TAIL:
            dropped = _LOG_TAIL.popleft()
            total -= len(dropped)
        # optional tee to file
        if _LOG_FILE_PATH:
            try:
                with open(_LOG_FILE_PATH, "a", encoding="utf-8", errors="replace") as f:
                    f.write(s)
            except Exception:
                pass

def worker_log_tail(max_bytes: int = 4000) -> str:
    with _LOG_LOCK:
        buf = "".join(_LOG_TAIL)
    # return last max_bytes
    if len(buf) <= max_bytes:
        return buf
    return buf[-max_bytes:]

def _pump_stream(proc: subprocess.Popen):
    # single stream because we pipe stderr->stdout
    try:
        if proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            _log_tail_append(line)
    except Exception as _e:
        _log_tail_append(f"[worker:pump] stream error: {_e}\n")

def _wait_health(port: int, timeout_s: float = 10.0) -> bool:
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                data = json.loads(r.read().decode())
                if data.get("ok"):
                    return True
        except Exception:
            time.sleep(0.2)
    return False

def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def start_worker(os_name: str, backend: str, port: int | None = None) -> dict:
    """
    Launches the already-provisioned runtime worker (CPU/CUDA/…).
    Works in both dev and packaged (Electron + PyInstaller) by deriving the
    packaged source root (…/resources/_internal) from the backend executable.
    """
    import sys
    from pathlib import Path

    global _worker_proc, _worker_info

    # Stop any existing worker first
    if _worker_proc and _worker_proc.poll() is None:
        stop_worker()

    # Ensure the selected backend is provisioned (creates venv + wheels if needed)
    ensure_provisioned(os_name, backend)

    # Pick a free port if not provided
    if port is None:
        port = pick_free_port()

    # ---------- Locate packaged source root ----------
    # When packaged, sys.executable points at .../resources/localmind-backend.exe
    # Our code (ext, aimodel, etc.) is under .../resources/_internal
    try:
        exe_dir = Path(sys.executable).resolve().parent
        internal_root = (exe_dir / "_internal").resolve()
    except Exception:
        internal_root = Path(".").resolve()

    internal_exists = internal_root.exists()

    # ---------- Build environment for the worker ----------
    _, py, _ = venv_paths(os_name, backend)
    env = os.environ.copy()
    env["BACKEND"] = backend
    env["LM_RUNTIME_PYTHON"] = str(py)
    env["PYTHONIOENCODING"] = "utf-8"  # avoid Windows console encoding issues

    # Make packaged modules importable inside the worker (ext, aimodel, …)
    if internal_exists:
        env["PYTHONPATH"] = (
            str(internal_root)
            + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        )

    # Backend-specific accelerators
    if backend == "cpu":
        env["LLAMA_ACCEL"] = "cpu"
        env["CUDA_VISIBLE_DEVICES"] = "-1"
        env.pop("GGML_CUDA", None)
    elif backend == "cuda":
        env["LLAMA_ACCEL"] = "cuda"
        env["GGML_CUDA"] = "1"
        env.pop("CUDA_VISIBLE_DEVICES", None)
    elif backend == "metal":
        env["LLAMA_ACCEL"] = "metal"
    elif backend == "rocm":
        env["LLAMA_ACCEL"] = "hip"

    # Use _internal as the CWD so relative imports/assets resolve
    worker_cwd = str(internal_root if internal_exists else Path(".").resolve())

    # ---------- Launch worker ----------
    _worker_proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "ext.ai_service:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=worker_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    # Pump logs to in-memory tail
    t = Thread(target=_pump_stream, args=(_worker_proc,), name="lm-worker-log-pump", daemon=True)
    t.start()

    # Health check (quick fail with log tail if not healthy)
    if not _wait_health(port):
        tail = worker_log_tail(4000)
        try:
            _worker_proc.terminate()
        except Exception:
            pass
        raise RuntimeError("Worker failed health check.\n--- worker log tail ---\n" + tail)

    _worker_info = {"os": os_name, "backend": backend, "port": port}
    _log_tail_append(f"[worker] started {backend} at :{port} (cwd={worker_cwd})\n")
    return {"ok": True, **_worker_info}


def stop_worker() -> dict:
    global _worker_proc, _worker_info
    if _worker_proc and _worker_proc.poll() is None:
        try:
            _worker_proc.terminate()
            _worker_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _worker_proc.kill()
        except Exception as e:
            _log_tail_append(f"[worker:stop] error: {e}\n")
    _worker_proc = None
    info, _worker_info = _worker_info, None
    _log_tail_append("[worker] stopped\n")
    return {"ok": True, "last": info}

def status() -> dict:
    running = _worker_proc is not None and _worker_proc.poll() is None
    return {"running": running, "info": _worker_info}

# ----------------------------
# Backend detection and order (unchanged)
# ----------------------------
def _cmd_ok(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

def has_cuda() -> bool:
    s = platform.system().lower()
    if _cmd_ok(["nvidia-smi"]):
        return True
    if s.startswith("win"):
        try:
            ctypes.WinDLL("nvcuda.dll")
            return True
        except Exception:
            return False
    elif s.startswith("linux"):
        lib = find_library("cuda") or "/usr/lib/x86_64-linux-gnu/libcuda.so.1"
        try:
            if lib and Path(lib).exists():
                return True
            ctypes.CDLL("libcuda.so.1")
            return True
        except Exception:
            return False
    return False

def has_rocm() -> bool:
    s = platform.system().lower()
    if not s.startswith("linux"):
        return False
    if _cmd_ok(["rocminfo"]):
        return True
    return Path("/opt/rocm").exists()

def has_vulkan() -> bool:
    s = platform.system().lower()
    if s.startswith("win"):
        try:
            ctypes.WinDLL("vulkan-1.dll")
            return True
        except Exception:
            return False
    elif s.startswith("linux"):
        try:
            ctypes.CDLL("libvulkan.so.1")
            return True
        except Exception:
            return False
    elif s.startswith("darwin"):
        try:
            ctypes.CDLL("libvulkan.1.dylib")
            return True
        except Exception:
            return False
    return False

def has_metal() -> bool:
    return platform.system().lower().startswith("darwin")

def _detect_order() -> list[str]:
    osn = current_os()
    if osn == "mac":
        order = []
        if has_metal(): order.append("metal")
        order.append("cpu")
        return order
    if osn == "windows":
        order = []
        if has_cuda(): order.append("cuda")
        if has_vulkan(): order.append("vulkan")
        order.append("cpu")
        return order
    if osn == "linux":
        order = []
        if has_cuda(): order.append("cuda")
        if has_rocm(): order.append("rocm")
        if has_vulkan(): order.append("vulkan")
        order.append("cpu")
        return order
    return ["cpu"]

def preferred_order_or_detect() -> list[str]:
    osn = current_os()
    forced = (os.getenv("LM_FORCE_BACKEND") or "").strip().lower()
    if forced:
        return [forced]
    pref = (SETTINGS.get("runtime", {}).get("preferred_backend") or "").lower()
    allow_fb = SETTINGS.get("runtime", {}).get("allow_fallback", True)
    detected = _detect_order()
    if pref:
        if not allow_fb:
            return [pref]
        rest = [b for b in detected if b != pref]
        return [pref] + rest
    return detected

def switch_auto(preferred: list[str] | None = None) -> dict:
    os_name = current_os()
    order = preferred or preferred_order_or_detect()
    provisioned = set(list_provisioned_backends(os_name))
    candidates = [b for b in order if b in provisioned]
    if not candidates and "cpu" in VALID.get(os_name, []):
        candidates = ["cpu"]
    last_err = None
    for b in candidates:
        try:
            ensure_provisioned(os_name, b)
            out = start_worker(os_name, b)
            try:
                _, py, _ = venv_paths(os_name, b)
                ACTIVE_JSON.parent.mkdir(parents=True, exist_ok=True)
                ACTIVE_JSON.write_text(json.dumps({"python": str(py), "backend": b, "os": os_name}, indent=2))
            except Exception:
                pass
            return {"ok": True, **out}
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(
        f"No runtime backend could be started (tried: {candidates})"
        f"{f' — last error: {last_err}' if last_err else ''}"
    )
