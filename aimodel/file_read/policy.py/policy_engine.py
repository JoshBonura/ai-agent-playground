# policy_engine.py
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from typing import Any, Callable, Dict, Optional

from .policy_config import Policy, PolicyOverrides, compute_policy
from .capability_probe import CapabilityReport, probe_capabilities
from .model_runtime import current_model_info


class PolicyEngine:
    """
    Central adaptive policy manager.

    Responsibilities
    - Run a hardware/model capability probe and compute an execution Policy
    - Expose the current Policy to callers (router, packer, web)
    - Periodically refresh in the background (configurable interval)
    - Allow runtime overrides (e.g., admin knob, user preference)
    - Notify subscribers when the policy changes
    """

    def __init__(self, *, refresh_interval_sec: int = 600) -> None:
        self._lock = asyncio.Lock()
        self._policy: Optional[Policy] = None
        self._report: Optional[CapabilityReport] = None
        self._overrides: PolicyOverrides = {}
        self._refresh_interval = max(10, int(refresh_interval_sec))
        self._bg_task: Optional[asyncio.Task] = None
        self._subscribers: set[Callable[[Policy], None]] = set()

    # ------------------------------- lifecycle -------------------------------
    async def start(self) -> None:
        """Start background refresh loop (idempotent)."""
        async with self._lock:
            if self._bg_task and not self._bg_task.done():
                return
            # initial compute immediately
            await self._refresh_locked(reason="startup")
            # spawn periodic refresher
            self._bg_task = asyncio.create_task(self._run_loop(), name="policy_engine_loop")

    async def stop(self) -> None:
        task = self._bg_task
        if task:
            task.cancel()
            try:
                await task
            except Exception:
                pass
            self._bg_task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._refresh_interval)
                async with self._lock:
                    await self._refresh_locked(reason="periodic")
            except asyncio.CancelledError:
                break
            except Exception:
                # keep the loop alive; next tick will retry
                pass

    # ------------------------------ core updates -----------------------------
    async def refresh_now(self, *, reason: str = "manual") -> Policy:
        async with self._lock:
            await self._refresh_locked(reason=reason)
            assert self._policy is not None
            return self._policy

    async def _refresh_locked(self, *, reason: str) -> None:
        # 1) Probe system/model
        report = await probe_capabilities()

        # 2) Pull current model context length if available
        try:
            info = current_model_info() or {}
            cfg = (info.get("config") or {}) if isinstance(info, dict) else {}
            if cfg.get("nCtx"):
                report.model_ctx = int(cfg.get("nCtx"))
        except Exception:
            pass

        # 3) Merge env overrides (lowest precedence of overrides)
        env_overrides = _read_env_overrides()
        merged_overrides = {**env_overrides, **self._overrides}

        # 4) Compute policy
        new_policy = compute_policy(report, overrides=merged_overrides)

        # 5) Set & notify if changed
        changed = (self._policy is None) or (asdict(self._policy) != asdict(new_policy))
        self._policy = new_policy
        self._report = report
        if changed:
            for fn in list(self._subscribers):
                try:
                    fn(new_policy)
                except Exception:
                    pass

    # ------------------------------ subscriptions ----------------------------
    def subscribe(self, fn: Callable[[Policy], None]) -> None:
        self._subscribers.add(fn)

    def unsubscribe(self, fn: Callable[[Policy], None]) -> None:
        self._subscribers.discard(fn)

    # -------------------------------- getters --------------------------------
    def get_policy(self) -> Policy:
        if self._policy is None:
            # best-effort synchronous bootstrap (blocking probe via loop.run_until?)
            # In async servers, call start() at app startup to avoid this path.
            raise RuntimeError("PolicyEngine not started. Call await policy_engine.start().")
        return self._policy

    def get_report(self) -> CapabilityReport:
        if self._report is None:
            raise RuntimeError("PolicyEngine not started. Call await policy_engine.start().")
        return self._report

    def snapshot(self) -> Dict[str, Any]:
        p = self.get_policy()
        r = self.get_report()
        return {
            "policy": asdict(p),
            "report": asdict(r),
            "refreshIntervalSec": self._refresh_interval,
        }

    # -------------------------------- overrides ------------------------------
    async def set_overrides(self, overrides: PolicyOverrides) -> Policy:
        async with self._lock:
            self._overrides = dict(overrides or {})
            await self._refresh_locked(reason="overrides")
            return self._policy  # type: ignore[return-value]

    async def clear_overrides(self) -> Policy:
        return await self.set_overrides({})


# --------------------------- module-level singleton ---------------------------
_policy_engine: Optional[PolicyEngine] = None


def get_engine() -> PolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        # Default interval can be nudged via env
        refresh = int(os.getenv("LOCALAI_POLICY_REFRESH_SEC", "600") or "600")
        _policy_engine = PolicyEngine(refresh_interval_sec=refresh)
    return _policy_engine


async def start_engine() -> None:
    await get_engine().start()


# ------------------------------ env utilities ------------------------------

def _read_env_overrides() -> PolicyOverrides:
    """Read optional JSON from LOCALAI_POLICY_OVERRIDES.

    Example:
      export LOCALAI_POLICY_OVERRIDES='{"inference.maxTokens":768,"web.k":4}'
    """
    raw = os.getenv("LOCALAI_POLICY_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    # Accept either flat keys or nested dicts
    # (compute_policy can handle both due to dot-walking in its merge)
    if not isinstance(data, dict):
        return {}
    return data  # type: ignore[return-value]


# ----------------------------- handy convenience -----------------------------

async def current_policy() -> Policy:
    eng = get_engine()
    if eng._policy is None:
        await eng.start()
    return eng.get_policy()


async def current_snapshot() -> Dict[str, Any]:
    eng = get_engine()
    if eng._policy is None:
        await eng.start()
    return eng.snapshot()
