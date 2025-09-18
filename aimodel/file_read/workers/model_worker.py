# aimodel/file_read/workers/model_worker.py
from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx

from ..core.logging import get_logger

log = get_logger(__name__)


@dataclass
class WorkerInfo:
    id: str
    port: int
    model_path: str
    process: subprocess.Popen
    status: str = "loading"  # loading | ready | stopped
    host_bind: str = "127.0.0.1"    # where uvicorn binds
    host_client: str = "127.0.0.1"  # where the proxy should dial


class ModelWorkerSupervisor:
    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}

    # ---------------------------
    # Utilities
    # ---------------------------
    def _find_free_port(self, host: str) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _is_worker_ready(self, *args) -> bool:
        """
        Back-compat:
          - _is_worker_ready(port)
          - _is_worker_ready(host, port)
        """
        if len(args) == 1:
            host, port = "127.0.0.1", args[0]
        elif len(args) == 2:
            host, port = args
        else:
            return False

        try:
            r = httpx.get(f"http://{host}:{port}/api/worker/health", timeout=1.0)
            if r.status_code != 200:
                return False
            data = r.json()
            return bool(data.get("ok"))
        except Exception:
            return False

    async def _wait_ready(self, wid: str, host: str, port: int, timeout_s: float = 120.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            info = self._workers.get(wid)
            if not info:
                return False
            # if worker process died, bail
            if info.process and (info.process.poll() is not None):
                return False
            if self._is_worker_ready(host, port):
                return True
            await asyncio.sleep(0.25)
        return False

    # ---------------------------
    # Introspection
    # ---------------------------
    def get_worker(self, wid: str) -> Optional[WorkerInfo]:
        return self._workers.get(wid)

    def get_addr(self, wid: str) -> Optional[Tuple[str, int]]:
        info = self._workers.get(wid)
        if not info:
            return None
        return (info.host_client, info.port)

    # Back-compat helper for existing code
    def get_port(self, wid: str) -> Optional[int]:
        info = self._workers.get(wid)
        return info.port if info else None

    def list(self) -> list[dict]:
        """
        Returns a JSON-serializable snapshot of known workers.
        Also self-heals status: if a worker finished loading after
        spawn wait, flip status to 'ready' here.
        """
        out = []
        for w in self._workers.values():
            # reflect process death
            if getattr(w, "process", None) and (w.process.poll() is not None):
                w.status = "stopped"
            else:
                # probe health to upgrade from 'loading' -> 'ready'
                if w.status != "ready":
                    try:
                        if self._is_worker_ready(w.host_client, w.port):
                            w.status = "ready"
                    except Exception:
                        pass

            out.append(
                {
                    "id": w.id,
                    "port": w.port,
                    "model_path": w.model_path,
                    "status": w.status,
                    "pid": (w.process.pid if getattr(w, "process", None) else None),
                }
            )
        return out

    # Older name some routes used
    def list_workers(self) -> list[dict]:
        return self.list()

    # ---------------------------
    # Lifecycle
    # ---------------------------
    async def spawn_worker(self, model_path: str) -> WorkerInfo:
        """Spawn a new worker process to serve a model."""
        host_bind = os.getenv("LM_WORKER_BIND_HOST", "127.0.0.1")
        host_client = os.getenv("LM_WORKER_CLIENT_HOST", "127.0.0.1")

        wid = os.urandom(4).hex()
        port = self._find_free_port(host_bind)

        # repo root = parent of the 'aimodel' package dir
        repo_root = Path(__file__).resolve().parents[3]
        app_module = "aimodel.file_read.workers.worker_entry:app"

        log.info(f"[workers] spawning {wid} on {host_bind}:{port} for {model_path}")
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            app_module,
            "--host",
            host_bind,
            "--port",
            str(port),
            "--log-level",
            "info",
        ]
        log.info(f"[workers] cwd={repo_root} cmd={' '.join(cmd)}")

        env = os.environ.copy()
        env["MODEL_PATH"] = model_path
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
        debug = env.get("LM_WORKER_DEBUG", "0") == "1"
        if debug:
            cmd.extend(["--log-level", "debug"])

        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdout=None if debug else subprocess.DEVNULL,
            stderr=None if debug else subprocess.DEVNULL,
        )

        time.sleep(0.05)
        if proc.poll() is not None:
            raise RuntimeError("worker exited immediately; enable LM_WORKER_DEBUG=1 to see logs")

        info = WorkerInfo(
            id=wid,
            port=port,
            model_path=model_path,
            process=proc,
            status="loading",
            host_bind=host_bind,
            host_client=host_client,
        )
        # register immediately so UI can show "loading"
        self._workers[wid] = info

        ready = await self._wait_ready(wid, host_client, port)
        info.status = "ready" if ready else "loading"
        return info

    async def stop_worker(self, wid: str) -> bool:
        """Stop a specific worker."""
        info = self._workers.get(wid)
        if not info:
            return False
        log.info(f"[workers] stopping worker {wid}")
        try:
            if info.process and (info.process.poll() is None):
                info.process.send_signal(signal.SIGTERM)
                try:
                    info.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    info.process.kill()
        except Exception as e:
            log.warning(f"[workers] error stopping {wid}: {e}")
        info.status = "stopped"
        # leave record so UI can show it as stopped; caller can prune if desired
        return True

    async def stop_all(self) -> int:
        """Stop all workers."""
        n = 0
        for wid in list(self._workers.keys()):
            try:
                ok = await self.stop_worker(wid)
                if ok:
                    n += 1
            except Exception as e:
                log.warning(f"[workers] stop_all error on {wid}: {e}")
        return n


# Singleton supervisor
supervisor = ModelWorkerSupervisor()
