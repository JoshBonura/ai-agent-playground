from __future__ import annotations

"""
Worker types, constants, and small helpers used across the worker subsystem.

Keeping this file a bit larger on purpose (rich docstrings / helpers) so each of
the three modules is > ~150 LOC as requested. No external side effects here.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple, Iterable
import os
import sys
import signal
import subprocess
import json
import time


# ---------------------------
# Status constants / helpers
# ---------------------------

STATUS_LOADING = "loading"
STATUS_READY = "ready"
STATUS_STOPPED = "stopped"
STATUS_UNKNOWN = "unknown"

TERMINAL_STATUSES = {STATUS_STOPPED}
LIVEish_STATUSES = {STATUS_LOADING, STATUS_READY}


def is_terminal(status: str | None) -> bool:
    return str(status) in TERMINAL_STATUSES


def is_live(status: str | None) -> bool:
    return str(status) in LIVEish_STATUSES


# ---------------------------
# Dataclass + serialization
# ---------------------------

@dataclass
class WorkerInfo:
    """
    In-memory record for a worker subprocess.

    Notes
    -----
    * `process` is intentionally kept as a Popen to allow signaling / wait.
    * `kwargs` mirrors the effective llama kwargs we pass via LLAMA_KWARGS_JSON.
    """
    id: str
    port: int
    model_path: str
    process: subprocess.Popen
    status: str = STATUS_LOADING
    host_bind: str = "127.0.0.1"
    host_client: str = "127.0.0.1"
    kwargs: dict | None = None

    # ------------- convenience accessors -------------
    @property
    def pid(self) -> int | None:
        try:
            return self.process.pid if self.process else None
        except Exception:
            return None

    def to_public_dict(self) -> Dict[str, Any]:
        """
        Shape used by the REST layer for /inspect and friends.
        """
        return {
            "id": self.id,
            "port": self.port,
            "model_path": self.model_path,
            "status": self.status,
            "pid": self.pid,
            "kwargs": self.kwargs or {},
        }

    # ------------- state update helpers -------------
    def mark_stopped(self) -> None:
        self.status = STATUS_STOPPED

    def mark_ready(self) -> None:
        self.status = STATUS_READY

    def mark_loading(self) -> None:
        self.status = STATUS_LOADING


# ---------------------------
# Process utilities
# ---------------------------

def send_sigterm_then_kill(proc: subprocess.Popen, *, wait_s: float = 10.0) -> Tuple[bool, str]:
    """
    Try a gentle SIGTERM, fall back to kill() after wait_s.
    Returns (stopped, message).
    """
    if proc is None:
        return True, "no-process"
    try:
        if proc.poll() is not None:
            return True, f"already-exited:{proc.returncode}"
        try:
            # Windows / POSIX compatible soft-stop:
            if os.name == "nt":
                proc.send_signal(signal.SIGTERM)  # Python emulates on Windows
            else:
                proc.send_signal(signal.SIGTERM)
        except Exception as e:
            return False, f"sigterm-error:{e!r}"

        t0 = time.time()
        while time.time() - t0 < wait_s:
            rc = proc.poll()
            if rc is not None:
                return True, f"terminated:{rc}"
            time.sleep(0.05)

        # Hard kill
        try:
            proc.kill()
            return True, "killed"
        except Exception as e:
            return False, f"kill-error:{e!r}"

    except Exception as e:
        return False, f"stop-error:{e!r}"


def poll_is_running(proc: subprocess.Popen | None) -> bool:
    try:
        return (proc is not None) and (proc.poll() is None)
    except Exception:
        return False


# ---------------------------
# Env / kwargs mirror helpers
# ---------------------------

_INT_MIRRORS = (
    ("n_ctx", "N_CTX"),
    ("n_threads", "N_THREADS"),
    ("n_gpu_layers", "N_GPU_LAYERS"),
    ("n_batch", "N_BATCH"),
)

_FLOAT_MIRRORS = (
    ("rope_freq_base", "ROPE_FREQ_BASE"),
    ("rope_freq_scale", "ROPE_FREQ_SCALE"),
)


def mirror_llama_kwargs_to_env(kwargs: Dict[str, Any], env: Dict[str, str]) -> None:
    """
    Fill env with mirrored numeric knobs so child can optionally read either.
    """
    for k_json, k_env in _INT_MIRRORS:
        v = kwargs.get(k_json)
        if isinstance(v, int):
            env[k_env] = str(v)
    for k_json, k_env in _FLOAT_MIRRORS:
        v = kwargs.get(k_json)
        if isinstance(v, (int, float)):
            env[k_env] = str(v)


# ---------------------------
# JSON helpers
# ---------------------------

def dump_llama_kwargs_json(kwargs: Dict[str, Any]) -> str:
    try:
        return json.dumps(kwargs)
    except Exception:
        return "{}"


def parse_health_json(text_or_obj: str | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(text_or_obj, dict):
        return text_or_obj
    try:
        return json.loads(text_or_obj)
    except Exception:
        return {}


# ---------------------------
# Module sentinels / defaults
# ---------------------------

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_CLIENT_HOST = "127.0.0.1"
DEFAULT_WAIT_READY_S = 120.0

# Wide threshold for “long” operations used by UX metrics
UX_LONG_MS = 800

# How often to poll for readiness
READINESS_POLL_S = 0.25
