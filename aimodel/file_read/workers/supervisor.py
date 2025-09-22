from __future__ import annotations

"""
Process supervisor for model workers.

This module wires together:
  * worker_types.WorkerInfo + helpers
  * guardrail.compute_llama_settings
  * spawn/stop/list/kill-by-path APIs used by the FastAPI router

Public surface:
  - class ModelWorkerSupervisor
  - instance `supervisor` (drop-in replacement for your previous import)
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import httpx

from ..core.logging import get_logger
from ..core.settings import SETTINGS
from ..services.accel_prefs import read_pref

from .worker_types import (
    WorkerInfo, STATUS_LOADING, STATUS_READY, STATUS_STOPPED,
    poll_is_running, send_sigterm_then_kill, mirror_llama_kwargs_to_env,
    dump_llama_kwargs_json, DEFAULT_BIND_HOST, DEFAULT_CLIENT_HOST,
    DEFAULT_WAIT_READY_S, READINESS_POLL_S,
)
from .worker_guardrail import compute_llama_settings

log = get_logger(__name__)


class ModelWorkerSupervisor:
    """
    Holds WorkerInfo records and controls their lifecycle.
    """

    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}
        self._kill_on_spawn_paths: set[str] = set()
        # diagnostics (read by API on conflict)
        self._last_guardrail_diag: dict = {}

    # --------------------------
    # Lookup / snapshot helpers
    # --------------------------

    def _find_free_port(self, host: str) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _is_worker_ready(self, *args) -> bool:
        if len(args) == 1:
            host, port = DEFAULT_CLIENT_HOST, args[0]
        elif len(args) == 2:
            host, port = args
        else:
            return False
        try:
            r = httpx.get(f"http://{host}:{port}/api/worker/health", timeout=0.2)
            if r.status_code != 200:
                return False
            data = r.json()
            return bool(data.get("ok"))
        except Exception:
            return False

    def _find_workers_by_path(self, model_path: str) -> List[WorkerInfo]:
        out: List[WorkerInfo] = []
        for w in self._workers.values():
            if getattr(w, "model_path", None) == model_path and w.status != STATUS_STOPPED:
                out.append(w)
        return out

    # --------------------------
    # Public introspection API
    # --------------------------

    def list(self) -> list[dict]:
        out = []
        for w in self._workers.values():
            if getattr(w, "process", None) and (w.process.poll() is not None):
                w.mark_stopped()
            else:
                if w.status != STATUS_READY:
                    try:
                        if self._is_worker_ready(w.host_client, w.port):
                            w.mark_ready()
                    except Exception:
                        pass
            out.append(w.to_public_dict())
        return out

    def get_worker(self, wid: str) -> Optional[WorkerInfo]:
        return self._workers.get(wid)

    def get_addr(self, wid: str) -> Optional[Tuple[str, int]]:
        info = self._workers.get(wid)
        if not info:
            return None
        return (info.host_client, info.port)

    def get_port(self, wid: str) -> Optional[int]:
        info = self._workers.get(wid)
        return info.port if info else None

    # --------------------------
    # Kill APIs
    # --------------------------

    async def _kill_worker_info(self, info: WorkerInfo) -> bool:
        t0 = time.perf_counter()
        log.info(
            "[workers.kill] begin id=%s pid=%s status=%s path=%s",
            info.id, getattr(info.process, "pid", None), info.status, info.model_path
        )
        ok, msg = send_sigterm_then_kill(info.process)
        if not ok:
            log.warning("[workers] error stopping %s: %s", info.id, msg)
            return False
        info.mark_stopped()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info(
            "[workers.kill] finished id=%s status=%s result=%s dt=%.1fms",
            info.id, info.status, msg, dt_ms
        )
        return True

    async def stop_worker(self, wid: str) -> bool:
        info = self._workers.get(wid)
        if not info:
            return False
        return await self._kill_worker_info(info)

    async def stop_all(self) -> int:
        n = 0
        for wid in list(self._workers.keys()):
            try:
                ok = await self.stop_worker(wid)
                if ok:
                    n += 1
            except Exception as e:
                log.warning(f"[workers] stop_all error on {wid}: {e}")
        return n

    async def request_kill_by_path(self, model_path: str, include_ready: bool = True) -> dict:
        t0 = time.perf_counter()
        log.info(
            "[workers.kill_by_path] incoming modelPath=%s includeReady=%s",
            model_path, include_ready
        )

        killed_ids: list[str] = []
        # Try to kill any matching, currently-live worker
        for info in list(self._workers.values()):
            if info.model_path == model_path and info.status != STATUS_STOPPED:
                if include_ready or info.status == STATUS_LOADING:
                    ok = await self._kill_worker_info(info)
                    if ok:
                        killed_ids.append(info.id)

        # If nothing was killed, queue kill-on-spawn (once)
        queued_now = False
        if not killed_ids:
            if model_path not in self._kill_on_spawn_paths:
                self._kill_on_spawn_paths.add(model_path)
                queued_now = True
                log.info(
                    "[workers.kill_by_path] queued kill for path=%s (no live worker matched)",
                    model_path
                )

        res = {"killed": killed_ids, "queued": (model_path in self._kill_on_spawn_paths)}
        dt_ms = (time.perf_counter() - t0) * 1000.0
        log.info(
            "[workers.kill_by_path] outcome modelPath=%s killed=%s queued=%s dt=%.1fms",
            model_path, killed_ids, res["queued"], dt_ms
        )
        return res

    # --------------------------
    # Spawn path
    # --------------------------

    async def _wait_ready(self, wid: str, host: str, port: int, timeout_s: float = DEFAULT_WAIT_READY_S) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            info = self._workers.get(wid)
            if not info:
                return False
            if info.process and (info.process.poll() is not None):
                return False
            # IMPORTANT: run the synchronous health probe in a thread so the event loop stays free
            is_ok = await asyncio.to_thread(self._is_worker_ready, host, port)
            if is_ok:
                return True
            await asyncio.sleep(READINESS_POLL_S)
        log.info(
            "[workers.wait_ready] timeout wid=%s host=%s port=%s after %.1fs",
            wid, host, port, timeout_s
        )
        return False


    async def spawn_worker(self, model_path: str, llama_kwargs: dict | None = None) -> WorkerInfo:
        host_bind = os.getenv("LM_WORKER_BIND_HOST", DEFAULT_BIND_HOST)
        host_client = os.getenv("LM_WORKER_CLIENT_HOST", DEFAULT_CLIENT_HOST)
        pref = read_pref()
        wid = os.urandom(4).hex()
        port = self._find_free_port(host_bind)
        repo_root = Path(__file__).resolve().parents[3]
        app_module = "aimodel.file_read.workers.worker_entry:app"
        log.info(
            f"[workers] spawning {wid} on {host_bind}:{port} for {model_path} "
            f"(accel={pref.accel}, n_gpu_layers={pref.n_gpu_layers})"
        )

        cmd = [
            sys.executable, "-m", "uvicorn", app_module,
            "--host", host_bind, "--port", str(port),
            "--log-level", "info",
        ]

        env = os.environ.copy()
        env["MODEL_PATH"] = model_path
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        # Compute final llama settings (kwargs + env) with guardrails
        cleaned, env_patch, diag = await compute_llama_settings(model_path, llama_kwargs or {})
        self._last_guardrail_diag = (diag or {})

        env.update(env_patch)
        if isinstance(cleaned.get("main_gpu"), int) and (env.get("LLAMA_ACCEL") in {"cuda", "hip"}):
            env["LLAMA_DEVICE"] = str(int(cleaned["main_gpu"]))

        # Mirror knobs and pack JSON for the child
        mirror_llama_kwargs_to_env(cleaned, env)
        env["LLAMA_KWARGS_JSON"] = dump_llama_kwargs_json(cleaned)
        env["WORKER_ID"] = wid
        env["WORKER_HOST"] = host_client        
        env["WORKER_PORT"] = str(port)          
        debug = env.get("LM_WORKER_DEBUG", "0") == "1"
        if debug:
            cmd[-1] = "debug"

        t_spawn = time.perf_counter()
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdout=None if debug else subprocess.DEVNULL,
            stderr=None if debug else subprocess.DEVNULL,
        )
        # give the process a beat to crash if it's going to
        await asyncio.sleep(0.05)
        if proc.poll() is not None:
            raise RuntimeError("worker exited immediately; enable LM_WORKER_DEBUG=1 to see logs")

        info = WorkerInfo(
            id=wid,
            port=port,
            model_path=model_path,
            process=proc,
            status=STATUS_LOADING,
            host_bind=host_bind,
            host_client=host_client,
            kwargs=cleaned or {},
        )
        self._workers[wid] = info

        # Kill-on-spawn handling
        if model_path in self._kill_on_spawn_paths:
            dt_ms = (time.perf_counter() - t_spawn) * 1000.0
            log.info(
                "[workers.spawn] kill-on-spawn: stopping id=%s path=%s dt=%.1fms",
                wid, model_path, dt_ms
            )
            await self._kill_worker_info(info)
            self._kill_on_spawn_paths.discard(model_path)
            return info  # stopped info

        ready = await self._wait_ready(wid, host_client, port)
        info.status = STATUS_READY if ready else STATUS_LOADING
        return info


# Singleton
supervisor = ModelWorkerSupervisor()
