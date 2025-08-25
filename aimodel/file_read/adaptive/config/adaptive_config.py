# aimodel/file_read/runtime/adaptive_config.py
from __future__ import annotations
import os, shutil, subprocess, platform
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

try:
    import psutil
except Exception:
    psutil = None
try:
    import torch
except Exception:
    torch = None

from .paths import read_settings

def _env_bool(k:str, default:bool)->bool:
    v = os.getenv(k)
    if v is None: return default
    return v.strip().lower() in ("1","true","yes","on")

def _cpu_count()->int:
    try:
        import multiprocessing as mp
        return max(1, mp.cpu_count() or os.cpu_count() or 1)
    except Exception:
        return os.cpu_count() or 1

def _avail_ram()->Optional[int]:
    if not psutil: return None
    try: return int(psutil.virtual_memory().available)
    except Exception: return None

def _cuda_vram()->Optional[int]:
    if torch and torch.cuda.is_available():
        try:
            dev = torch.cuda.current_device()
            props = torch.cuda.get_device_properties(dev)
            return int(props.total_memory)
        except Exception:
            pass
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi","--query-gpu=memory.total","--format=csv,noheader,nounits"],
                text=True, stderr=subprocess.DEVNULL, timeout=2.0
            )
            mb = max(int(x.strip()) for x in out.strip().splitlines() if x.strip())
            return mb * 1024 * 1024
        except Exception:
            return None
    return None

def _gpu_kind()->str:
    if _cuda_vram(): return "cuda"
    if torch and getattr(torch.backends,"mps",None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default

def _pick_dtype_quant(device: str, a: Dict[str, Any], vram_bytes: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    dq = a.get("dtype_quant", {}) if isinstance(a, dict) else {}
    if device == "cuda":
        tiers = dq.get("cuda_tiers") or []
        vram_gb = (vram_bytes or 0) / (1024**3)
        best = None
        for t in sorted(tiers, key=lambda x: float(x.get("min_vram_gb", 0)), reverse=True):
            if vram_gb >= _safe_float(t.get("min_vram_gb"), 0.0):
                best = t
                break
        if best:
            return best.get("dtype"), best.get("quant")
        return dq.get("cuda_default_dtype"), dq.get("cuda_default_quant")
    if device == "mps":
        return dq.get("mps_default_dtype"), None
    return dq.get("cpu_default_dtype"), dq.get("cpu_default_quant")

def _pick_kv(device: str, a: Dict[str, Any], vram_bytes: Optional[int]) -> Optional[str]:
    kv = a.get("kv_cache", {}) if isinstance(a, dict) else {}
    if device == "cuda":
        tiers = kv.get("cuda_tiers") or []
        vram_gb = (vram_bytes or 0) / (1024**3)
        best = None
        for t in sorted(tiers, key=lambda x: float(x.get("min_vram_gb", 0)), reverse=True):
            if vram_gb >= _safe_float(t.get("min_vram_gb"), 0.0):
                best = t
                break
        if best:
            return best.get("dtype")
        return kv.get("cuda_default")
    if device == "mps":
        return kv.get("mps_default")
    return kv.get("cpu_default")

def _pick_capacity(device: str, a: Dict[str, Any], vram_bytes: Optional[int], threads:int) -> tuple[int,int,Optional[int]]:
    cap = a.get("capacity", {}) if isinstance(a, dict) else {}
    if device == "cuda":
        tiers = cap.get("cuda_tiers") or []
        vram_gb = (vram_bytes or 0) / (1024**3)
        best = None
        for t in sorted(tiers, key=lambda x: float(x.get("min_vram_gb", 0)), reverse=True):
            if vram_gb >= _safe_float(t.get("min_vram_gb"), 0.0):
                best = t
                break
        if best:
            return int(best.get("seq_len") or 0), int(best.get("batch") or 1), int(best.get("n_gpu_layers") or 0)
        return 0, 1, 0
    if device == "mps":
        m = cap.get("mps", {})
        return int(m.get("seq_len") or 0), int(m.get("batch") or 1), 0
    cpu = cap.get("cpu", {})
    seq_len = int(cpu.get("seq_len") or 0)
    batch = 1
    by = cpu.get("batch_by_threads") or []
    best = None
    for t in sorted(by, key=lambda x: int(x.get("min_threads", 0)), reverse=True):
        if threads >= int(t.get("min_threads") or 0):
            best = t
            break
    if best:
        batch = int(best.get("batch") or 1)
    return seq_len, batch, 0

def _gpu_mem_fraction(device:str, a: Dict[str, Any]) -> float:
    table = a.get("gpu_fraction", {}) if isinstance(a, dict) else {}
    v = table.get(device)
    return _safe_float(v, 0.0)

def _torch_flags(device:str, a: Dict[str, Any]) -> tuple[bool,bool]:
    flags = a.get("flags", {}) if isinstance(a, dict) else {}
    flash = bool(flags.get("enable_flash_attn_cuda")) if device == "cuda" else False
    tc = bool(flags.get("use_torch_compile_on_cuda_linux")) if (device == "cuda" and platform.system().lower()=="linux") else False
    return flash, tc

def _threads(a: Dict[str, Any]) -> tuple[int,int,int,int]:
    policy = a.get("cpu_threads_policy", {}) if isinstance(a, dict) else {}
    mode = str(policy.get("mode") or "").lower()
    ncpu = _cpu_count()
    if mode == "fixed":
        v = int(policy.get("value") or max(1, ncpu-1))
        t = max(1, min(v, ncpu))
    elif mode == "percent":
        pct = _safe_float(policy.get("value"), 0.0)
        t = max(1, min(ncpu, int(round(ncpu*pct/100.0))))
        if t < 1: t = 1
    else:
        t = max(1, ncpu-1)
    intra = t
    inter = max(1, ncpu//2)
    return ncpu, t, intra, inter

@dataclass
class AdaptiveConfig:
    device: str
    dtype: Optional[str]
    quant: Optional[str]
    kv_cache_dtype: Optional[str]
    max_seq_len: int
    max_batch_size: int
    gpu_memory_fraction: float
    cpu_threads: int
    torch_intraop_threads: int
    torch_interop_threads: int
    enable_flash_attn: bool
    use_torch_compile: bool
    total_vram_bytes: Optional[int]
    avail_ram_bytes: Optional[int]
    cpu_count: int
    def as_dict(self)->Dict[str,Any]:
        return asdict(self)

def compute_adaptive_config()->AdaptiveConfig:
    settings = read_settings()
    a = settings.get("adaptive", {}) if isinstance(settings, dict) else {}
    device = _gpu_kind()
    vram = _cuda_vram() if device=="cuda" else None
    ram = _avail_ram()
    ncpu, threads, intra, inter = _threads(a)
    dtype, quant = _pick_dtype_quant(device, a, vram)
    kv = _pick_kv(device, a, vram)
    seq_len, batch, n_gpu_layers = _pick_capacity(device, a, vram, threads)
    frac = _gpu_mem_fraction(device, a)
    flash, tcompile = _torch_flags(device, a)
    return AdaptiveConfig(
        device=device,
        dtype=dtype,
        quant=quant,
        kv_cache_dtype=kv,
        max_seq_len=int(seq_len or 0),
        max_batch_size=int(batch or 1),
        gpu_memory_fraction=frac,
        cpu_threads=threads,
        torch_intraop_threads=intra,
        torch_interop_threads=inter,
        enable_flash_attn=flash,
        use_torch_compile=tcompile,
        total_vram_bytes=vram,
        avail_ram_bytes=ram,
        cpu_count=ncpu
    )
