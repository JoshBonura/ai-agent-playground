# run_backend.py
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

import platformdirs
import uvicorn

print("[boot] python:", sys.executable, flush=True)

PREF_API = (8001, 5321)
API_RANGE = (10240, 11240)
BIND_HOST = "0.0.0.0"

print("[data] LOCALMIND_DATA_DIR =", os.getenv("LOCALMIND_DATA_DIR"))

DATA_ROOT = pathlib.Path(
    os.getenv("LOCALMIND_DATA_DIR") or platformdirs.user_data_dir("localmind", roaming=True)
)

os.environ.setdefault("LOCALMIND_DATA_DIR", str(DATA_ROOT))

RUNTIME_DIR = DATA_ROOT / ".runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
PORTS_PATH = RUNTIME_DIR / "ports.json"


def _free(p: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind((BIND_HOST, p))
            return True
        except OSError:
            return False


def choose_port() -> int:
    for p in PREF_API:
        if _free(p):
            return p
    lo, hi = API_RANGE
    for p in random.sample(range(lo, hi), 900):
        if _free(p):
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
        return {"ok": True}

    @r.get("/info")
    async def _info(request: Request):
        ip = getattr(request.app.state, "lan_ip", "127.0.0.1")
        port = int(getattr(request.app.state, "port", 8001))
        return {"ip": ip, "port": port, "url": f"http://{ip}:{port}"}

    app.include_router(r)


def mount_frontend(app):
    from pathlib import Path

    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

        @app.exception_handler(404)
        async def spa_fallback(request: Request, exc):
            p = request.url.path
            accept = request.headers.get("accept", "")

            if p.startswith(
                (
                    "/openapi.json",
                    "/docs",
                    "/docs/oauth2-redirect",
                    "/redoc",
                    "/api",
                    "/metrics",
                    "/health",
                    "/info",
                )
            ):
                return JSONResponse({"detail": "Not Found"}, status_code=404)

            if "application/json" in accept or p.endswith(".json"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)

            return FileResponse(dist / "index.html")


def preflight_openapi_or_point_to_offender(app):
    import inspect
    from typing import Annotated, get_args, get_origin

    from fastapi import Request as _Req
    from fastapi.params import (Body, Cookie, File, Form, Header, Param, Path,
                                Query)

    def _bad_request_param(p: inspect.Parameter) -> bool:
        ann = p.annotation
        inner = get_args(ann)[0] if get_origin(ann) is Annotated else ann
        if inner is not _Req:
            return False
        return (
            isinstance(p.default, (Param, Query, Body, Path, Header, Cookie, File, Form))
            or p.default is not inspect._empty
        )

    print("[preflight] routes present:", len(getattr(app, "routes", [])))
    for r in getattr(app, "routes", []):
        fn = getattr(r, "endpoint", None)
        print(
            "  -", r.path, "->", getattr(fn, "__module__", "?") + "." + getattr(fn, "__name__", "?")
        )

    try:
        app.openapi_schema = None
        app.openapi()
        print("[preflight] OpenAPI OK")
        return
    except Exception as e:
        print("[preflight] OpenAPI FAILED:", repr(e))

    print("[preflight] scanning endpoints for illegal Request params…")
    offenders = []
    for r in getattr(app, "routes", []):
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
            print(f"❌ {path} -> {mod}.{name} {sig}")
        print("=============================")
    else:
        print(
            "[preflight] no obvious offenders found; the error may come from a dynamically-composed dependency"
        )


if __name__ == "__main__":
    try:
        print("[boot] choose_port", flush=True)
        PORT = choose_port()
        PORTS_PATH.write_text(json.dumps({"api_port": PORT}), encoding="utf-8")

        print("[boot] import app", flush=True)
        module, attr = "aimodel.file_read.app:app".split(":")
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
