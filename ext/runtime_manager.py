# ext/runtime_manager.py
from pathlib import Path
import platform as py_platform
import os, sys, json, subprocess, time, urllib.request

# Paths
REQ_ROOT    = Path("ext") / "requirements.txt"     # ext/requirements.txt/...
WHEELS_ROOT = Path("ext") / "wheels"               # ext/wheels/win/...
RUNTIMES_DIR = Path(".runtime") / "venvs"          # local venvs
# near top of ext/runtime_manager.py
WORKER_APP = os.getenv("WORKER_APP", "aimodel.file_read.app:app")  # <- your app module:path
WORKER_CWD = os.getenv("WORKER_CWD", ".")                          # repo root

OS_DIR = {"windows": "win", "linux": "linux", "mac": "mac"}

VALID = {
    "windows": ["cpu", "cuda", "vulkan"],
    "linux":   ["cpu", "cuda", "rocm", "vulkan"],
    "mac":     ["cpu", "metal"],
}

def current_os() -> str:
    s = py_platform.system().lower()
    if s.startswith("win"):    return "windows"
    if s.startswith("linux"):  return "linux"
    if s.startswith("darwin"): return "mac"
    raise RuntimeError(f"Unsupported OS: {s}")

def mapping(os_name: str, backend: str):
    if os_name not in VALID: raise ValueError(f"Unsupported OS {os_name}")
    if backend not in VALID[os_name]: raise ValueError(f"{backend} not valid for {os_name}")
    req = REQ_ROOT / f"{os_name}.{backend}.txt"
    wheels = WHEELS_ROOT / OS_DIR[os_name] / backend
    return req, wheels

def venv_paths(os_name: str, backend: str):
    vroot = RUNTIMES_DIR / os_name / backend / ".venv"
    if current_os() == "windows":
        py = vroot / "Scripts" / "python.exe"
        pip = vroot / "Scripts" / "pip.exe"
    else:
        py = vroot / "bin" / "python"
        pip = vroot / "bin" / "pip"
    return vroot, py, pip

def ensure_venv(os_name: str, backend: str, python_exe: str | None = None):
    vroot, py, pip = venv_paths(os_name, backend)
    if not vroot.exists():
        vroot.parent.mkdir(parents=True, exist_ok=True)
        base_py = python_exe or sys.executable
        subprocess.run([base_py, "-m", "venv", str(vroot)], check=True)
    return vroot, py, pip

def install_runtime(os_name: str, backend: str, python_exe: str | None = None):
    req, wheels = mapping(os_name, backend)
    if not wheels.exists():
        raise FileNotFoundError(f"Wheels folder missing: {wheels}")
    if not req.exists():
        raise FileNotFoundError(f"Requirements file missing: {req}")

    vroot, py, pip = ensure_venv(os_name, backend, python_exe)
    try:
        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    except subprocess.CalledProcessError:
        pass

    cmd = [str(pip), "install", "--no-index", "--find-links", str(wheels), "-r", str(req)]
    subprocess.run(cmd, check=True)

    stamp = {
        "platform": os_name,
        "backend": backend,
        "python": str(py),
        "req": str(req),
        "wheels": str(wheels),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    (vroot.parent / ".runtime.json").write_text(json.dumps(stamp, indent=2))
    return {"ok": True, "venv": str(vroot), "manifest": stamp}

# --- Worker launch/stop ---
_worker_proc = None
_worker_info = None

def _wait_health(port: int, timeout_s=10):
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if json.loads(r.read().decode()).get("ok"):
                    return True
        except Exception:
            time.sleep(0.2)
    return False

def start_worker(os_name: str, backend: str, port: int = 52111):
    global _worker_proc, _worker_info
    if _worker_proc and _worker_proc.poll() is None:
        raise RuntimeError("Worker already running; stop it first.")

    _, py, _ = venv_paths(os_name, backend)
    env = os.environ.copy()
    env["BACKEND"] = backend
    if backend == "cuda":   env["GGML_CUDA"]   = "1"
    if backend == "vulkan": env["GGML_VULKAN"] = "1"
    if backend == "metal":  env["GGML_METAL"]  = "1"

    # Launch from ext/ folder so ai_service.py is found
    _worker_proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "ai_service:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd="ext", env=env
    )

    if not _wait_health(port):
        raise RuntimeError("Worker failed health check")

    _worker_info = {"os": os_name, "backend": backend, "port": port}
    return {"ok": True, **_worker_info}

def stop_worker():
    global _worker_proc, _worker_info
    if _worker_proc and _worker_proc.poll() is None:
        _worker_proc.terminate()
        try:
            _worker_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _worker_proc.kill()
    _worker_proc = None
    info, _worker_info = _worker_info, None
    return {"ok": True, "last": info}

def status():
    running = _worker_proc is not None and _worker_proc.poll() is None
    return {"running": running, "info": _worker_info}
