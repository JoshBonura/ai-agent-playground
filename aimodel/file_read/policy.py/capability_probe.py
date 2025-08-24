# aimodel/file_read/services/capability_probe.py
from __future__ import annotations
import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple

# Optional imports – all guarded
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

# Local runtime hooks
try:
    from ..model_runtime import current_model_info
except Exception:  # pragma: no cover
    def current_model_info() -> Dict[str, Any]:  # type: ignore
        return {"loaded": False, "config": None}

# --------------------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------------------

@dataclass
class GPUInfo:
    index: int
    name: str
    vram_total_mb: int
    vram_free_mb: int
    driver: Optional[str] = None
    temperature_c: Optional[float] = None

@dataclass
class CapabilityReport:
    # Hardware/OS
    os: str
    arch: str
    backend: str  # "cuda"|"rocm"|"mps"|"cpu"
    cpu_cores: int
    load_1m: Optional[float]
    ram_total_mb: int
    ram_free_mb: int

    # GPUs
    gpu_count: int
    gpus: List[GPUInfo] = field(default_factory=list)

    # Model/runtime config snapshot
    model_ctx_tokens: int
    n_threads: int
    n_gpu_layers: int
    n_batch: int

    # App/runtime signals (optional, filled by integrators)
    active_sessions: int = 0
    p95_latency_ms_decode: Optional[float] = None
    p95_latency_ms_tokenize: Optional[float] = None
    tokenizer_tps: Optional[float] = None

    ts_unix: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # dataclasses of GPUs are already dicts because of asdict recursion
        return d

# --------------------------------------------------------------------------------------
# Helpers – CPU/RAM
# --------------------------------------------------------------------------------------

def _cpu_cores() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _load_1m() -> Optional[float]:
    try:
        if hasattr(os, "getloadavg"):
            return float(os.getloadavg()[0])
    except Exception:
        pass
    return None


def _ram_tot_free_mb() -> Tuple[int, int]:
    # Prefer psutil when present
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()  # type: ignore[attr-defined]
            return int(vm.total // (1024 * 1024)), int(vm.available // (1024 * 1024))
        except Exception:
            pass

    # Fallbacks by OS
    try:
        if platform.system() == "Linux":
            total = free = 0
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(re.findall(r"\d+", line)[0]) // 1024
                    elif line.startswith("MemAvailable:"):
                        free = int(re.findall(r"\d+", line)[0]) // 1024
            if total and free:
                return total, free
        elif platform.system() == "Darwin":
            # macOS: use vm_stat (pages) as a rough estimate
            out = subprocess.check_output(["vm_stat"], text=True)
            m = re.findall(r"page size of (\d+) bytes", out)
            page = int(m[0]) if m else 4096
            pages_free = 0
            for line in out.splitlines():
                if line.startswith("Pages free") or line.startswith("Pages speculative"):
                    pages_free += int(re.findall(r"\d+", line)[0])
                if line.startswith("Pages active") or line.startswith("Pages inactive") or line.startswith("Pages wired down"):
                    # not used directly; we'll compute total via sysctl
                    pass
            total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            free_bytes = pages_free * page
            return total_bytes // (1024 * 1024), free_bytes // (1024 * 1024)
        elif platform.system() == "Windows":
            out = subprocess.check_output(["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/Value"], text=True)
            kv = dict(
                (k.strip(), v.strip())
                for k, v in (line.split("=", 1) for line in out.splitlines() if "=" in line)
            )
            total_kib = int(kv.get("TotalVisibleMemorySize", "0") or 0)
            free_kib = int(kv.get("FreePhysicalMemory", "0") or 0)
            return total_kib // 1024, free_kib // 1024
    except Exception:
        pass

    # Ultimate fallback
    return 0, 0

# --------------------------------------------------------------------------------------
# Helpers – GPU detection
# --------------------------------------------------------------------------------------

_DEF_TIMEOUT = 2.5  # seconds for small probe calls


def _run(cmd: List[str]) -> Optional[str]:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=_DEF_TIMEOUT)
    except Exception:
        return None


def _probe_nvidia() -> Tuple[str, List[GPUInfo]]:
    """Return (driver, gpus[]) if nvidia-smi is available, else ("", [])."""
    if not shutil.which("nvidia-smi"):
        return "", []

    q = _run([
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free,driver_version,temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not q:
        return "", []

    gpus: List[GPUInfo] = []
    driver = None
    for line in q.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            total_mb = int(parts[2])
            free_mb = int(parts[3])
            driver = parts[4]
            temp_c = float(parts[5]) if len(parts) > 5 else None
            gpus.append(GPUInfo(index=idx, name=name, vram_total_mb=total_mb, vram_free_mb=free_mb, driver=driver, temperature_c=temp_c))
        except Exception:
            continue
    return (driver or ""), gpus


def _probe_rocm() -> Tuple[str, List[GPUInfo]]:
    # Try rocm-smi JSON first; fall back to text parse
    exe = shutil.which("rocm-smi") or shutil.which("amd-smi")
    if not exe:
        return "", []

    out = _run([exe, "--showproductname", "--showid", "--showmeminfo", "vram", "--showtemp"])
    if not out:
        return "", []

    # Very loose parsing (rocm-smi text varies)
    gpus: List[GPUInfo] = []
    total_mb = free_mb = None
    name = None
    idx = -1
    for line in out.splitlines():
        if re.search(r"GPU\s*\[?\d+\]?", line):
            idx += 1
            total_mb = free_mb = None
            name = None
        m_name = re.search(r"Product\s*Name\s*:\s*(.*)$", line)
        if m_name:
            name = m_name.group(1).strip()
        m_total = re.search(r"VRAM Total:\s*(\d+)\s*MiB", line)
        if m_total:
            total_mb = int(m_total.group(1))
        m_free = re.search(r"VRAM Free:\s*(\d+)\s*MiB", line)
        if m_free:
            free_mb = int(m_free.group(1))
        if name and total_mb is not None and free_mb is not None:
            gpus.append(GPUInfo(index=max(idx, len(gpus)), name=name, vram_total_mb=total_mb, vram_free_mb=free_mb))
            name = None
            total_mb = free_mb = None
    return ("rocm" if gpus else ""), gpus


def _probe_mps() -> Tuple[str, List[GPUInfo]]:
    if platform.system() != "Darwin":
        return "", []
    # Quick check for Apple GPU via system_profiler
    if not shutil.which("system_profiler"):
        return "", []
    out = _run(["system_profiler", "SPDisplaysDataType"])
    if not out:
        return "", []
    # We can't get VRAM free reliably here; report total per adapter when available
    gpus: List[GPUInfo] = []
    idx = -1
    for block in out.split("\n\n"):
        if "Chipset Model" in block or "Apple" in block:
            idx += 1
            name_m = re.search(r"Chipset Model:\s*(.*)", block)
            vram_m = re.search(r"VRAM.*:\s*(\d+(?:\.\d+)?)\s*GB", block)
            name = name_m.group(1).strip() if name_m else "Apple GPU"
            total_mb = int(float(vram_m.group(1)) * 1024) if vram_m else 0
            gpus.append(GPUInfo(index=idx, name=name, vram_total_mb=total_mb, vram_free_mb=0))
    return ("mps" if gpus else ""), gpus


# --------------------------------------------------------------------------------------
# Probe – aggregate
# --------------------------------------------------------------------------------------

def _detect_backend_and_gpus() -> Tuple[str, List[GPUInfo]]:
    # Priority: CUDA > ROCm > MPS > CPU
    drv, gpus = _probe_nvidia()
    if gpus:
        return "cuda", gpus

    drv, gpus = _probe_rocm()
    if gpus:
        return "rocm", gpus

    drv, gpus = _probe_mps()
    if gpus:
        return "mps", gpus

    return "cpu", []


def _model_cfg_snapshot() -> Tuple[int, int, int, int]:
    try:
        info = current_model_info() or {}
        cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
        return (
            int(cfg.get("nCtx") or 4096),
            int(cfg.get("nThreads") or 0),
            int(cfg.get("nGpuLayers") or 0),
            int(cfg.get("nBatch") or 0),
        )
    except Exception:
        return (4096, 0, 0, 0)


def probe_once() -> CapabilityReport:
    os_name = platform.system()
    arch = platform.machine()

    backend, gpus = _detect_backend_and_gpus()
    cpu_cores = _cpu_cores()
    load_1m = _load_1m()
    ram_total_mb, ram_free_mb = _ram_tot_free_mb()

    nctx, nthreads, ngpu_layers, nbatch = _model_cfg_snapshot()

    return CapabilityReport(
        os=os_name,
        arch=arch,
        backend=backend,
        cpu_cores=cpu_cores,
        load_1m=load_1m,
        ram_total_mb=ram_total_mb,
        ram_free_mb=ram_free_mb,
        gpu_count=len(gpus),
        gpus=gpus,
        model_ctx_tokens=nctx,
        n_threads=nthreads,
        n_gpu_layers=ngpu_layers,
        n_batch=nbatch,
    )

# --------------------------------------------------------------------------------------
# Public API – cached access + periodic refresh
# --------------------------------------------------------------------------------------

_refresh_interval_s = 12.0
_cache_ttl_s = 9.0
_latest_lock = threading.RLock()
_latest: Optional[CapabilityReport] = None
_task: Optional[asyncio.Task] = None


def collect_capabilities(force: bool = False) -> CapabilityReport:
    global _latest
    with _latest_lock:
        if not force and _latest and (time.time() - _latest.ts_unix) < _cache_ttl_s:
            return _latest
        rep = probe_once()
        _latest = rep
        return rep


async def _periodic_loop():  # pragma: no cover
    global _latest
    while True:
        try:
            rep = probe_once()
            with _latest_lock:
                _latest = rep
        except Exception:
            # Keep going on probe errors; next loop may succeed
            pass
        await asyncio.sleep(_refresh_interval_s)


def start_periodic_refresh(interval_s: float = 12.0, cache_ttl_s: float = 9.0) -> None:
    """Start a background task that keeps the capability snapshot fresh.

    Safe to call multiple times; it will start once.
    """
    global _task, _refresh_interval_s, _cache_ttl_s
    _refresh_interval_s = max(3.0, float(interval_s))
    _cache_ttl_s = max(1.0, float(cache_ttl_s))

    if _task and not _task.done():
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running (e.g., during unit tests); create a temporary loop thread
        def _runner():
            asyncio.run(_periodic_loop())
        t = threading.Thread(target=_runner, name="cap_probe", daemon=True)
        t.start()
        return

    _task = loop.create_task(_periodic_loop(), name="capability_probe")


# --------------------------------------------------------------------------------------
# Debug helpers
# --------------------------------------------------------------------------------------

def debug_dump() -> str:
    rep = collect_capabilities()
    return json.dumps(rep.to_dict(), indent=2)

