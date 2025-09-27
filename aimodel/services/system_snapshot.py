from __future__ import annotations
import asyncio, time
from typing import Any, Dict, Optional
from ..core.logging import get_logger
from .system_collectors import read_system_resources_sync

log = get_logger(__name__)

_SNAPSHOT: Optional[Dict[str, Any]] = None
_LAST_TS: float = 0.0
_LOCK = asyncio.Lock()

async def _collect_once() -> Dict[str, Any]:
    return await asyncio.to_thread(read_system_resources_sync, log)

async def poll_system_snapshot(period_sec: float = 1.0) -> None:
    global _SNAPSHOT, _LAST_TS
    try:
        # ---- One-time warmup so cpu_percent(interval=None) has a baseline ----
        try:
            import psutil  # type: ignore
            # prime baseline (returns immediately)
            await asyncio.to_thread(psutil.cpu_percent, None)
            # small delay so the first real sample isn't 0.0
            await asyncio.sleep(0.25)
        except Exception:
            pass
        # ---------------------------------------------------------------------

        while True:
            snap = await _collect_once()
            snap["ts"] = time.time()
            async with _LOCK:
                _SNAPSHOT = snap
                _LAST_TS = snap["ts"]
            await asyncio.sleep(period_sec)
    except asyncio.CancelledError:
        # clean exit on shutdown
        raise
    except Exception as e:
        log.warning("[system] poll error: %s", e)
        # brief backoff to avoid tight error loop
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise

async def get_system_snapshot() -> Dict[str, Any]:
    async with _LOCK:
        return dict(_SNAPSHOT or {
            "cpu": {}, "ram": {}, "gpus": [], "gpuSource": "none", "platform": "", "ts": 0.0
        })


# --- helper: VRAM projection for guardrails ---
async def get_vram_projection(model_gb: float, kv_gb: float, overhead_gb: float = 0.2):
    """
    Returns a tuple (proj_gb, free_gb, total_gb).
    proj_gb = model + kv + overhead.
    Reads GPU0 stats from the latest system snapshot.
    """
    snap = await get_system_snapshot()
    gpus = snap.get("gpus") or []
    if not gpus:
        return (model_gb + kv_gb + overhead_gb, 0.0, 0.0)

    gpu0 = gpus[0]
    total = float(gpu0.get("total") or 0) / (1024**3)  # bytes→GiB
    free  = float(gpu0.get("free") or 0) / (1024**3)
    proj  = model_gb + kv_gb + overhead_gb
    return (proj, free, total)
