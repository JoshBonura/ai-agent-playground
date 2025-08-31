# place at: aimodel/file_read/runtime/warmup.py  (or services/warmup.py if you chose Option B)

from __future__ import annotations
import asyncio, time
from typing import Optional, Dict, Any

from ..core.settings import SETTINGS
from ..runtime.model_runtime import ensure_ready, get_llm
from ..services.cancel import GEN_SEMAPHORE

_warmup_task: Optional[asyncio.Task] = None

async def _warmup_llm_once() -> Dict[str, Any]:
    t0 = time.perf_counter()
    ensure_ready()
    try:
        got = await asyncio.wait_for(GEN_SEMAPHORE.acquire(), timeout=0.01)
    except asyncio.TimeoutError:
        return {"llmSec": 0.0, "skipped": True}
    if not got:
        return {"llmSec": 0.0, "skipped": True}
    try:
        llm = get_llm()
        llm.create_chat_completion(messages=[{"role":"user","content":"ok"}], max_tokens=1, temperature=0.0, stream=False)
        return {"llmSec": round(time.perf_counter() - t0, 4), "skipped": False}
    except Exception:
        return {"llmSec": round(time.perf_counter() - t0, 4), "error": True}
    finally:
        try:
            GEN_SEMAPHORE.release()
        except Exception:
            pass

async def _warmup_web_once() -> Dict[str, Any]:
    tel: Dict[str, Any] = {"queries": []}
    if not bool(SETTINGS.get("web_enabled", True)):
        tel["skipped"] = True
        return tel
    k           = int(SETTINGS.get("warmup_web_k", 2))
    timeout_sec = float(SETTINGS.get("warmup_timeout_sec", 6))
    queries     = list(SETTINGS.get("warmup_queries") or [])
    try:
        from ..web.router_ai import decide_web_and_fetch
    except Exception:
        tel["error"] = "web_stack_unavailable"
        return tel
    llm = get_llm()
    t0 = time.perf_counter()
    for q in queries[:3]:
        try:
            block, web_tel = await asyncio.wait_for(decide_web_and_fetch(llm, q, k=k), timeout=timeout_sec)
            tel["queries"].append({"q": q, "chars": len(block or ""), **(web_tel or {})})
        except Exception:
            tel["queries"].append({"q": q, "error": True})
    tel["totalFetchSec"] = round(time.perf_counter() - t0, 4)
    return tel

async def warmup_once() -> Dict[str, Any]:
    eff = SETTINGS.effective()
    out: Dict[str, Any] = {}
    if bool(eff.get("warmup_llm_enabled", True)):
        out["llm"] = await _warmup_llm_once()
    if bool(eff.get("warmup_web_enabled", False)):
        out["web"] = await _warmup_web_once()
    return out

async def warmup_periodic(stop_ev: asyncio.Event) -> None:
    eff = SETTINGS.effective()
    interval = max(60, int(eff.get("warmup_on_interval_sec", 900)))
    jitter   = min(15, max(0, int(eff.get("warmup_jitter_sec", 5))))
    while not stop_ev.is_set():
        try:
            await warmup_once()
        except Exception:
            pass
        try:
            delay = interval + (asyncio.get_running_loop().time() % (jitter or 1))
            await asyncio.wait_for(stop_ev.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue

def start_warmup_runner(loop: asyncio.AbstractEventLoop) -> asyncio.Event:
    stop_ev = asyncio.Event()
    if bool(SETTINGS.get("warmup_enabled", True)):
        loop.create_task(warmup_periodic(stop_ev), name="warmup_periodic")
    return stop_ev

def stop_warmup_runner(stop_ev: Optional[asyncio.Event]) -> None:
    if stop_ev is not None:
        stop_ev.set()
