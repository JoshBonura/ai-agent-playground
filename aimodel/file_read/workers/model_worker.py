from __future__ import annotations

import asyncio
import json
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
    host_bind: str = "127.0.0.1"
    host_client: str = "127.0.0.1"
    kwargs: dict | None = None          # ← echo of llama kwargs sent to worker

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

    def get_port(self, wid: str) -> Optional[int]:
        info = self._workers.get(wid)
        return info.port if info else None

    def list(self) -> list[dict]:
        out = []
        for w in self._workers.values():
            if getattr(w, "process", None) and (w.process.poll() is not None):
                w.status = "stopped"
            else:
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
                    "kwargs": w.kwargs or {},
                }
            )
        return out

    # ---------------------------
    # Lifecycle
    # ---------------------------
    async def spawn_worker(self, model_path: str, llama_kwargs: dict | None = None) -> WorkerInfo:
        """Spawn a new worker process to serve a model."""
        host_bind = os.getenv("LM_WORKER_BIND_HOST", "127.0.0.1")
        host_client = os.getenv("LM_WORKER_CLIENT_HOST", "127.0.0.1")

        wid = os.urandom(4).hex()
        port = self._find_free_port(host_bind)
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
        env = os.environ.copy()
        env["MODEL_PATH"] = model_path
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        # Pass structured kwargs to the worker
        cleaned = dict(llama_kwargs or {})
        try:
            env["LLAMA_KWARGS_JSON"] = json.dumps(cleaned)
        except Exception:
            env["LLAMA_KWARGS_JSON"] = "{}"

        # For quick visibility in logs, also mirror some common ones as envs
        def _mirror_int(key_json: str, key_env: str):
            v = cleaned.get(key_json)
            if isinstance(v, int):
                env[key_env] = str(v)

        def _mirror_float(key_json: str, key_env: str):
            v = cleaned.get(key_json)
            if isinstance(v, (int, float)):
                env[key_env] = str(v)

        _mirror_int("n_ctx", "N_CTX")
        _mirror_int("n_threads", "N_THREADS")
        _mirror_int("n_gpu_layers", "N_GPU_LAYERS")
        _mirror_int("n_batch", "N_BATCH")
        _mirror_float("rope_freq_base", "ROPE_FREQ_BASE")
        _mirror_float("rope_freq_scale", "ROPE_FREQ_SCALE")

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
            kwargs=cleaned or {},
        )
        self._workers[wid] = info

        ready = await self._wait_ready(wid, host_client, port)
        info.status = "ready" if ready else "loading"
        return info

    async def stop_worker(self, wid: str) -> bool:
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
        return True

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

# Singleton supervisor
supervisor = ModelWorkerSupervisor()
