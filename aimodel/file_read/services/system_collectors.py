from __future__ import annotations
import subprocess, csv, io, platform
from typing import Any, Dict

def _read_gpu_via_nvidia_smi(log) -> list[dict[str, Any]]:
    """
    Ask nvidia-smi for GPU telemetry. Returns [] on error.
    Called by a background poller thread, not in a request path.
    """
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, check=True
        )
        out = proc.stdout.strip()
        if not out:
            return []
        reader = csv.reader(io.StringIO(out))
        gpus = []
        for row in reader:
            if not row or len(row) < 6:
                continue
            idx, name, mem_total, mem_used, mem_free, util = row[:6]
            try:
                gpus.append({
                    "index": int(idx),
                    "name": name.strip(),
                    "memoryTotalBytes": int(mem_total) * 1024 * 1024,
                    "memoryUsedBytes": int(mem_used) * 1024 * 1024,
                    "memoryFreeBytes": int(mem_free) * 1024 * 1024,
                    "utilPercent": float(util),
                })
            except Exception:
                continue
        return gpus
    except Exception as e:
        try:
            log.info("[system] nvidia-smi failed: %r", e)
        except Exception:
            pass
        return []

def read_system_resources_sync(log) -> Dict[str, Any]:
    """
    Synchronous collectors bundled together.
    Runs in a background thread (never in the request path).
    """
    data: Dict[str, Any] = {"cpu": {}, "ram": {}, "gpus": []}

    # CPU/RAM (psutil)
    try:
        import psutil  # type: ignore

        # RAM snapshot (instantaneous)
        vm = psutil.virtual_memory()
        data["ram"] = {
            "totalBytes": int(vm.total),
            "availableBytes": int(vm.available),
            "usedBytes": int(vm.used),
            "percent": float(vm.percent),
        }

        # CPU: delta since last call (non-blocking). Do NOT re-prime here.
        cpu_pct = float(psutil.cpu_percent(interval=None))

        data["cpu"] = {
            "countPhysical": psutil.cpu_count(logical=False) or 0,
            "countLogical": psutil.cpu_count(logical=True) or 0,
            "percent": cpu_pct,
        }
    except Exception as e:
        try:
            log.info("[system] psutil not available: %r", e)
        except Exception:
            pass

    # GPU via nvidia-smi
    gpus = _read_gpu_via_nvidia_smi(log)
    if gpus:
        data["gpus"] = gpus
        data["gpuSource"] = "nvidia-smi"
    else:
        data["gpuSource"] = "none"

    # Helpful debug info
    data["platform"] = platform.platform()
    return data
