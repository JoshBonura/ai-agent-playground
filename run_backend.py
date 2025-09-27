from __future__ import annotations

import contextlib
import json
import os
import pathlib
import random
import socket
import sys
import traceback
from importlib import import_module

import uvicorn
import multiprocessing as mp
from multiprocessing import freeze_support, set_start_method

if getattr(sys, "frozen", False):
    RES_DIR = pathlib.Path(sys.executable).parent
    INTERNAL = RES_DIR / "_internal"
    if (INTERNAL / "aimodel").exists():
        os.environ["PYTHONPATH"] = str(INTERNAL) + os.pathsep + os.environ.get("PYTHONPATH", "")

IS_WIN = os.name == "nt"
IS_FROZEN = bool(getattr(sys, "frozen", False))
PID = os.getpid()
PPID = os.getppid()

def _safe_get_start_method() -> str:
    try:
        return mp.get_start_method(allow_none=True) or "<unset>"
    except Exception:
        return "<error>"

_forced_start_method = None
try:
    set_start_method("spawn")
    _forced_start_method = "spawn"
except (RuntimeError, ValueError):
    pass

if IS_WIN:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def _log_preamble():
    print("[boot] python:", sys.executable, flush=True)
    print(f"[boot] pid={PID} ppid={PPID} frozen={IS_FROZEN}", flush=True)
    print(f"[boot] mp.start_method(before)={_safe_get_start_method()}  forced={_forced_start_method}", flush=True)

_log_preamble()

def _where():
    import traceback as _tb
    return "".join(_tb.format_stack(limit=16))

def _enable_spawn_diagnostics():
    try:
        import faulthandler, signal
        faulthandler.enable(all_threads=True)
        print("[diag] faulthandler enabled", flush=True)
    except Exception as _e:
        print("[diag] faulthandler enable failed:", _e, flush=True)

    try:
        from multiprocessing.util import log_to_stderr
        _mp_logger = log_to_stderr()
        level = os.getenv("LM_MP_LOG_LEVEL", "INFO")
        import logging as _logging
        _mp_logger.setLevel(getattr(_logging, str(level).upper(), _logging.INFO))
        print(f"[diag] mp logger enabled level={_mp_logger.level}", flush=True)
    except Exception as _e:
        print("[diag] mp logger setup failed:", _e, flush=True)

    try:
        _OrigProcess = mp.Process
        class _LoggingProcess(_OrigProcess):
            def __init__(self, *a, **kw):
                tgt = kw.get("target")
                name = getattr(tgt, "__name__", None) if tgt else None
                mod  = getattr(tgt, "__module__", None) if tgt else None
                print(f"[mp.Process] spawn requested target={mod}.{name} args={len(a)} kwargs={list(kw.keys())}", flush=True)
                print("[mp.Process] caller stack (tail):\n" + _where(), flush=True)
                super().__init__(*a, **kw)
        mp.Process = _LoggingProcess
        print("[diag] hooked multiprocessing.Process", flush=True)
    except Exception as _e:
        print("[diag] hook mp.Process failed:", _e, flush=True)

    try:
        import concurrent.futures as cf
        _OrigPPE = cf.ProcessPoolExecutor
        class _LoggingPPE(_OrigPPE):
            def __init__(self, *a, **kw):
                mw = kw.get("max_workers", (a[0] if a else None))
                print(f"[ProcessPoolExecutor] created max_workers={mw}", flush=True)
                print("[ProcessPoolExecutor] caller stack (tail):\n" + _where(), flush=True)
                super().__init__(*a, **kw)
        cf.ProcessPoolExecutor = _LoggingPPE
        print("[diag] hooked concurrent.futures.ProcessPoolExecutor", flush=True)
    except Exception as _e:
        print("[diag] hook ProcessPoolExecutor failed:", _e, flush=True)

    try:
        import subprocess as _subp
        _OrigPopen = _subp.Popen
        def _LoggingPopen(*a, **kw):
            try:
                cmd = a[0] if a else kw.get("args")
            except Exception:
                cmd = "<unknown>"
            print(f"[subprocess.Popen] args={cmd}", flush=True)
            print("[subprocess.Popen] caller stack (tail):\n" + _where(), flush=True)
            return _OrigPopen(*a, **kw)
        _subp.Popen = _LoggingPopen
        print("[diag] hooked subprocess.Popen", flush=True)
    except Exception as _e:
        print("[diag] hook subprocess.Popen failed:", _e, flush=True)

    try:
        import asyncio as _asyncio
        _OrigCreateTask = _asyncio.create_task
        def _LoggingCreateTask(coro, *a, **kw):
            print(f"[asyncio.create_task] {getattr(coro, '__name__', str(coro))}", flush=True)
            print("[asyncio.create_task] caller stack (tail):\n" + _where(), flush=True)
            return _OrigCreateTask(coro, *a, **kw)
        _asyncio.create_task = _LoggingCreateTask
        print("[diag] hooked asyncio.create_task", flush=True)
    except Exception as _e:
        print("[diag] hook asyncio.create_task failed:", _e, flush=True)

    if os.getenv("LM_DIAG_TORCH", "1") != "0":
        try:
            import torch
            print(f"[torch] present version={getattr(torch, '__version__', '?')}", flush=True)
            try:
                from torch.utils.data import DataLoader as _TorchDL
                class _LoggingDL(_TorchDL):
                    def __init__(self, *a, **kw):
                        nw = kw.get("num_workers", 0)
                        print(f"[torch.DataLoader] num_workers={nw}", flush=True)
                        print("[torch.DataLoader] caller stack (tail):\n" + _where(), flush=True)
                        super().__init__(*a, **kw)
                import torch.utils.data as tud
                tud.DataLoader = _LoggingDL
                print("[diag] hooked torch.utils.data.DataLoader", flush=True)
            except Exception as _e:
                print("[diag] torch DataLoader hook failed:", _e, flush=True)
            try:
                import torch.multiprocessing as tmp
                print(f"[torch.multiprocessing] start_method(mp)={mp.get_start_method(allow_none=True)}", flush=True)
            except Exception as _e:
                print("[diag] torch.multiprocessing import failed:", _e, flush=True)
        except Exception as _e:
            print("[diag] torch not present / import failed:", _e, flush=True)

if os.getenv("LM_DIAG_SPAWN", "0") in ("1", "true", "TRUE", "yes", "on"):
    _enable_spawn_diagnostics()
    print("[diag] SPAWN DIAGNOSTICS ENABLED", flush=True)
else:
    print("[diag] spawn diagnostics disabled (LM_DIAG_SPAWN not set)", flush=True)

PREF_API = (8001, 5321)
API_RANGE = (10240, 11240)
BIND_HOST = "0.0.0.0"

print("[data] LOCALMIND_DATA_DIR =", os.getenv("LOCALMIND_DATA_DIR"))

try:
    import platformdirs
except Exception:
    platformdirs = None

if platformdirs:
    DEFAULT_DATA = platformdirs.user_data_dir("localmind", roaming=True)
else:
    DEFAULT_DATA = str(pathlib.Path.home() / ".localmind")

DATA_ROOT = pathlib.Path(os.getenv("LOCALMIND_DATA_DIR") or DEFAULT_DATA)
os.environ.setdefault("LOCALMIND_DATA_DIR", str(DATA_ROOT))

RUNTIME_DIR = DATA_ROOT / ".runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
PORTS_PATH = RUNTIME_DIR / "ports.json"
HEALTH_PATH = RUNTIME_DIR / "health.json"

def _free(p: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((BIND_HOST, p))
            return True
        except OSError:
            return False

def choose_port() -> int:
    print(f"[boot] choose_port prefer={PREF_API} fallback_range={API_RANGE}", flush=True)
    for p in PREF_API:
        if _free(p):
            print(f"[boot] choose_port -> picked preferred {p}", flush=True)
            return p
        else:
            print(f"[boot] choose_port -> preferred {p} in use", flush=True)
    lo, hi = API_RANGE
    for p in random.sample(range(lo, hi), min(900, max(1, hi - lo))):
        if _free(p):
            print(f"[boot] choose_port -> picked random {p}", flush=True)
            return p
    raise RuntimeError("No free port found")

def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass
    return ip

def ensure_health(app):
    from fastapi import APIRouter, Request
    r = APIRouter()
    @r.get("/health")
    async def _health():
        try:
            HEALTH_PATH.write_text(json.dumps({"ok": True, "pid": PID}), encoding="utf-8")
        except Exception:
            pass
        return {"ok": True, "pid": PID}
    @r.get("/healthz")
    async def _healthz():
        return {"ok": True, "pid": PID}
    @r.get("/info")
    async def _info(request: Request):
        ip = getattr(request.app.state, "lan_ip", "127.0.0.1")
        port = int(getattr(request.app.state, "port", 8001))
        return {"ip": ip, "port": port, "url": f"http://{ip}:{port}", "pid": PID, "frozen": IS_FROZEN}
    app.include_router(r)

def mount_frontend(app):
    from pathlib import Path
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    dist = Path(__file__).resolve().parent / "frontend" / "dist"
    print(f"[boot] frontend dist exists={dist.exists()} at={dist}", flush=True)
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
        @app.exception_handler(404)
        async def spa_fallback(request: Request, exc):
            p = request.url.path
            accept = request.headers.get("accept", "")
            if p.startswith(("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/api", "/metrics", "/health", "/info")):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            if "application/json" in accept or p.endswith(".json"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(dist / "index.html")

def preflight_openapi_or_point_to_offender(app):
    import inspect
    from typing import Annotated, get_args, get_origin
    from fastapi import Request as _Req
    from fastapi.params import Body, Cookie, File, Form, Header, Param, Path, Query
    def _bad_request_param(p: inspect.Parameter) -> bool:
        ann = p.annotation
        inner = get_args(ann)[0] if get_origin(ann) is Annotated else ann
        if inner is not _Req:
            return False
        return (
            isinstance(p.default, (Param, Query, Body, Path, Header, Cookie, File, Form))
            or p.default is not inspect._empty
        )
    routes = getattr(app, "routes", [])
    print("[preflight] routes present:", len(routes))
    for r in routes:
        fn = getattr(r, "endpoint", None)
        print("  -", r.path, "->", getattr(fn, "__module__", "?") + "." + getattr(fn, "__name__", "?"))
    try:
        app.openapi_schema = None
        app.openapi()
        print("[preflight] OpenAPI OK")
        return
    except Exception as e:
        print("[preflight] OpenAPI FAILED:", repr(e))
    print("[preflight] scanning endpoints for illegal Request params…")
    offenders = []
    for r in routes:
        fn = getattr(r, "endpoint", None)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
        except Exception:
            continue
        bads = [p for p in sig.parameters.values() if _bad_request_param(p)]
        if bads:
            offenders.append((r.path, fn.__module__, getattr(fn, "__name__", "<fn>"), str(sig)))
    if offenders:
        print("=== OFFENDERS (fix these) ===")
        for path, mod, name, sig in offenders:
            print(f" {path} -> {mod}.{name} {sig}")
        print("=============================")
    else:
        print("[preflight] no obvious offenders found; the error may be in a composed dependency")

if __name__ == "__main__":
    try:
        freeze_support()
        print(f"[mp] freeze_support() OK  start_method(now)={_safe_get_start_method()}", flush=True)
    except Exception as e:
        print(f"[mp] freeze_support() error: {e}", flush=True)
    try:
        proc = mp.current_process()
        print(f"[mp] current_process name={proc.name} pid={proc.pid}", flush=True)
    except Exception:
        pass
    try:
        print("[boot] choose_port", flush=True)
        PORT = choose_port()
        try:
            PORTS_PATH.write_text(json.dumps({"api_port": PORT}), encoding="utf-8")
            print(f"[boot] wrote {PORTS_PATH} -> {{'api_port': {PORT}}}", flush=True)
        except Exception as e:
            print(f"[boot] failed to write {PORTS_PATH}: {e}", flush=True)
        print("[boot] import app", flush=True)
        module, attr = "aimodel.app:app".split(":")
        app = getattr(import_module(module), attr)
        print("[boot] preflight OpenAPI", flush=True)
        preflight_openapi_or_point_to_offender(app)
        print("[boot] compute LAN IP", flush=True)
        IP = lan_ip()
        app.state.port = PORT
        app.state.lan_ip = IP
        print("[boot] wire helpers", flush=True)
        mount_frontend(app)
        ensure_health(app)
        print("\n==================== AI Agent ====================")
        print(f" Connect from phone:  http://{IP}:{PORT}")
        print(f" Your code (port):    {PORT}")
        print(" (Allow Windows Firewall for Private networks)")
        print("==================================================\n", flush=True)
        log_level = os.getenv("LOG_LEVEL", "info")
        print(f"[boot] start uvicorn (log_level={log_level})", flush=True)
        uvicorn.run(app, host=BIND_HOST, port=PORT, reload=False, workers=1, log_level=log_level)
        print("[boot] uvicorn exited", flush=True)
    except Exception as e:
        print("[fatal] run_backend.py crashed:", repr(e), flush=True)
        traceback.print_exc()
