# aimodel/file_read/services/system_collectors.py
from __future__ import annotations

import csv
import io
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List
import sys


def _resolve_nvidia_smi() -> str | None:
    p = shutil.which("nvidia-smi")
    if p:
        return p
    candidates = [
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _read_gpu_via_nvidia_smi(_log=None) -> List[Dict[str, Any]]:
    exe = _resolve_nvidia_smi()
    if not exe:
        return []

    try:
        proc = subprocess.run(
            [
                exe,
                "--query-gpu=index,uuid,name,compute_cap,driver_version,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        out = (proc.stdout or "").strip()
        if not out:
            return []

        gpus: List[Dict[str, Any]] = []
        for row in csv.reader(io.StringIO(out)):
            if not row or len(row) < 9:
                continue
            idx, uuid, name, compcap, drv, mem_total, mem_used, mem_free, util = row[:9]
            try:
                tot_b = int(mem_total) * 1024 * 1024
                used_b = int(mem_used) * 1024 * 1024
                free_b = int(mem_free) * 1024 * 1024
                try:
                    util_f = float(util)
                except Exception:
                    util_f = 0.0

                gpus.append(
                    {
                        "index": int(idx),
                        "uuid": (uuid or "").strip(),
                        "name": name.strip(),
                        "computeCapability": (compcap or "").strip(),
                        "driverVersion": (drv or "").strip(),
                        "memoryTotalBytes": tot_b,
                        "memoryUsedBytes": used_b,
                        "memoryFreeBytes": free_b,
                        "utilPercent": util_f,
                        "total": tot_b,
                        "used": used_b,
                        "backend": "CUDA",
                    }
                )
            except Exception:
                continue
        return gpus
    except Exception:
        return []


def _cpu_name(_log=None) -> str:
    sysname = platform.system().lower()
    try:
        import cpuinfo  # type: ignore
        info = cpuinfo.get_cpu_info() or {}
        brand = (info.get("brand_raw") or info.get("brand")) or ""
        if brand.strip():
            return brand.strip()
    except Exception:
        pass

    name = platform.processor() or platform.uname().processor
    if name and name.strip():
        return name.strip()

    if sysname == "windows":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                text=True,
                creationflags=0x08000000,
            ).strip()
            if out:
                return out
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "Name"],
                text=True,
                creationflags=0x08000000,
            )
            lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != "Name"]
            if lines:
                return lines[0]
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["reg", "query",
                 r"HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                 "/v", "ProcessorNameString"],
                text=True,
                creationflags=0x08000000,
            )
            m = re.search(r"ProcessorNameString\s+REG_SZ\s+(.+)", out)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    if sysname == "darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
            if out:
                return out
        except Exception:
            pass

    if sysname == "linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass

    return "CPU"


def _cpu_isa_linux_flags() -> list[str]:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
        m = re.search(r"flags\s*:\s*(.*)", txt)
        if not m:
            return []
        fl = set(m.group(1).split())
        keep = []
        for k in ("avx", "avx2", "avx512f", "sse4_2", "sse4_1"):
            if k in fl:
                keep.append(k.upper())
        return keep
    except Exception:
        return []


def _cpu_isa_any() -> list[str]:
    sysname = platform.system().lower()
    if sysname == "linux":
        return _cpu_isa_linux_flags()

    flags: set[str] = set()
    try:
        import cpuinfo  # type: ignore
        info = cpuinfo.get_cpu_info() or {}
        for f in (info.get("flags") or []):
            if isinstance(f, str):
                flags.add(f.lower())
    except Exception:
        pass

    if sysname == "darwin":
        try:
            out1 = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.features"], text=True
            ).strip()
            out2 = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.leaf7_features"], text=True
            ).strip()
            for blob in (out1, out2):
                for f in blob.split():
                    flags.add(f.lower())
        except Exception:
            pass

    keep = []

    def keep_if(name: str, *aliases: str):
        for a in (name.lower(),) + tuple(x.lower() for x in aliases):
            if a in flags:
                keep.append(name.upper())
                return

    keep_if("AVX")
    keep_if("AVX2")
    keep_if("AVX512F", "avx512f", "avx512")
    keep_if("SSE4_2", "sse4.2", "sse4_2")
    keep_if("SSE4_1", "sse4.1", "sse4_1")
    keep_if("NEON")
    return keep


def _cpu_isa_windows_flags(_log=None) -> list[str]:
    try:
        import cpuinfo  # type: ignore
    except Exception:
        return []
    try:
        info = cpuinfo.get_cpu_info() or {}
        flags = set(info.get("flags") or [])
        keep_map = {
            "avx": "AVX",
            "avx2": "AVX2",
            "avx512f": "AVX512F",
            "sse4_1": "SSE4_1",
            "sse4_2": "SSE4_2",
        }
        return [keep_map[k] for k in keep_map.keys() if k in flags]
    except Exception:
        return []


def _detect_caps(data: Dict[str, Any]) -> Dict[str, bool]:
    sysname = platform.system().lower()
    caps = {"cpu": True, "cuda": False, "metal": False, "hip": False}
    if data.get("gpuSource") == "nvidia-smi" and (data.get("gpus") or []):
        caps["cuda"] = True
    if sysname == "darwin":
        caps["metal"] = True
    if sysname == "linux":
        if shutil.which("rocminfo") or shutil.which("rocm-smi") or Path("/opt/rocm").exists():
            caps["hip"] = True
    return caps


def _cpu_compat_status(cpu: Dict[str, Any]) -> Dict[str, Any]:
    arch = (cpu.get("arch") or "").strip().lower()
    isa = [str(x).lower() for x in (cpu.get("isa") or [])]
    if not arch:
        return {"status": "unknown", "reason": "CPU arch not detected"}

    def has(flag: str) -> bool:
        return flag.lower() in isa

    if arch in ("x86_64", "amd64", "x64"):
        if not isa:
            return {"status": "unknown", "reason": "ISA flags unavailable"}
        if has("avx") or has("avx2"):
            return {"status": "compatible", "reason": "x86_64 with AVX/AVX2"}
        return {"status": "incompatible", "reason": "x86_64 without AVX"}

    if arch in ("arm64", "aarch64"):
        if not isa:
            return {"status": "unknown", "reason": "ISA flags unavailable"}
        if has("neon"):
            return {"status": "compatible", "reason": "arm64 with NEON"}
        return {"status": "incompatible", "reason": "arm64 without NEON"}

    return {"status": "unknown", "reason": f"Unhandled arch: {arch}"}


def read_system_resources_sync(_log=None) -> Dict[str, Any]:
    data: Dict[str, Any] = {"cpu": {}, "ram": {}, "gpus": []}
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        data["ram"] = {
            "totalBytes": int(vm.total),
            "availableBytes": int(vm.available),
            "usedBytes": int(vm.used),
            "percent": float(vm.percent),
        }
        data["cpu"] = {
            "countPhysical": psutil.cpu_count(logical=False) or 0,
            "countLogical": psutil.cpu_count(logical=True) or 0,
            "percent": float(psutil.cpu_percent(interval=None)),
        }
    except Exception:
        data.setdefault("cpu", {"countPhysical": 0, "countLogical": 0, "percent": 0.0})
        data.setdefault("ram", {"totalBytes": 0, "availableBytes": 0, "usedBytes": 0, "percent": 0.0})

    try:
        data["cpu"]["name"] = _cpu_name()
    except Exception:
        data["cpu"]["name"] = "CPU"

    def _norm_arch(s: str | None) -> str:
        m = (s or "").strip().lower()
        if m in {"amd64", "x86_64", "x64"}:
            return "x86_64"
        if m in {"arm64", "aarch64"}:
            return "arm64"
        return s or "x86_64"

    try:
        data["cpu"]["arch"] = _norm_arch(platform.machine())
    except Exception:
        data["cpu"]["arch"] = "x86_64"

    try:
        sysname = platform.system().lower()
        if sysname == "linux":
            data["cpu"]["isa"] = _cpu_isa_linux_flags()
        elif sysname == "windows":
            data["cpu"]["isa"] = _cpu_isa_windows_flags()
        elif sysname == "darwin":
            data["cpu"]["isa"] = _cpu_isa_windows_flags()
        else:
            data["cpu"]["isa"] = []
    except Exception:
        data["cpu"]["isa"] = []

    gpus = _read_gpu_via_nvidia_smi()
    if gpus:
        data["gpus"] = gpus
        data["gpuSource"] = "nvidia-smi"
    else:
        data["gpuSource"] = "none"

    data["caps"] = _detect_caps(data)
    data["platform"] = platform.platform()

    try:
        sysname = platform.system().lower()
        if sysname == "windows":
            data["osFamily"] = "Windows"
        elif sysname == "darwin":
            data["osFamily"] = "macOS"
        elif sysname == "linux":
            data["osFamily"] = "Linux"
        else:
            data["osFamily"] = platform.system() or "OS"
    except Exception:
        data["osFamily"] = "OS"

    try:
        data["cpu"]["compat"] = _cpu_compat_status(data["cpu"])
    except Exception:
        data["cpu"]["compat"] = {"status": "unknown", "reason": "error"}

    try:
        from ..services.licensing_service import device_id as _dev_id
        data["device"] = {"id": _dev_id()}
    except Exception:
        pass

    return data
