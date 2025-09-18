# aimodel/file_read/app.py
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.routing import Mount

from .api.system import router as system_router
from .api.proxy_generate import router as worker_proxy_router
from .api import admins as admins_api
from .core.logging import get_logger, setup_logging
from .services.system_snapshot import poll_system_snapshot

setup_logging()
log = get_logger(__name__)

# 2) Now it’s safe to log during .env load
try:
    from dotenv import load_dotenv

    _ENV_PATH = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
except Exception as _e:
    log.info(f"[env] NOTE: could not load .env: {_e}")

from .adaptive.config.paths import bootstrap
from .api import settings as settings_router
from .api.admin_chats import router as admin_chats_router
from .api.auth_router import require_auth
from .api.auth_router import router as auth_router
from .api.billing import router as billing_router
from .api.chats import router as chats_router
from .api.generate_router import router as generate_router, cancel_router
from .api.licensing_router import router as licensing_router
from .api.metrics import router as metrics_router
from .api.models import router as models_router
from .api.rag import router as rag_router
from .api.model_workers import router as model_workers_router  # ✅ single import
from .workers.model_worker import supervisor  # ✅ single supervisor import

from .core import request_ctx
from .workers.retitle_worker import start_worker

KEYS = (
    "LIC_ED25519_PUB_HEX",
    "LIC_SERVER_BASE",
    "FIREBASE_WEB_API_KEY",
    "FIREBASE_PROJECT_ID",
)

log.info(f"[env] .env path={_ENV_PATH} exists={_ENV_PATH.exists()}")
for k in KEYS:
    v = os.getenv(k)
    log.info(f"[env] {k}: set={bool(v)} len={len(v or '')} head={(v or '')[:6]}")
bootstrap()

app = FastAPI()
app.state.bg_tasks = []  # keep handles to background tasks so we can cancel/await on shutdown

origins = [
    o.strip() for o in os.getenv("APP_CORS_ORIGIN", "http://localhost:5173").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

deps = [Depends(require_auth)]

# Core APIs
app.include_router(models_router)
app.include_router(chats_router, dependencies=deps)
app.include_router(generate_router, dependencies=deps)
app.include_router(settings_router.router, dependencies=deps)
app.include_router(rag_router, dependencies=deps)
app.include_router(metrics_router, dependencies=deps)
app.include_router(billing_router, dependencies=deps)
app.include_router(licensing_router, dependencies=deps)
app.include_router(admins_api.router, dependencies=deps)
app.include_router(auth_router)
app.include_router(admin_chats_router, dependencies=deps)
app.include_router(cancel_router, dependencies=deps)
app.include_router(worker_proxy_router, dependencies=deps)
app.include_router(system_router, dependencies=deps)
app.include_router(model_workers_router, dependencies=deps)

# --- Route dump (after all includes/mounts) ---
try:
    def _dump_routes():
        log.info("==== ROUTES (app) ====")
        for r in app.routes:
            methods = sorted(list(getattr(r, "methods", []) or []))
            path = getattr(r, "path", "")
            typ = type(r).__name__
            if isinstance(r, Mount) and hasattr(r.app, "routes"):
                log.info("[APP] %-12s %s type=%s (mounted app)", ",".join(methods), path, typ)
                for sr in r.app.routes:
                    sm = sorted(list(getattr(sr, "methods", []) or []))
                    sp = getattr(sr, "path", "")
                    log.info("       -> %-12s %s", ",".join(sm), sp)
            else:
                log.info("[APP] %-12s %s type=%s", ",".join(methods), path, typ)
        log.info("==== ROUTES END ====")
    _dump_routes()
except Exception as e:
    log.error("Failed to dump routes: %r", e)

# ---------- Serve built frontend (Vite 'dist') ----------
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIR / "assets"
INDEX_FILE = FRONTEND_DIR / "index.html"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR), html=False), name="assets")

@app.get("/", response_class=HTMLResponse)
async def _index():
    if INDEX_FILE.exists():
        return FileResponse(str(INDEX_FILE))
    return HTMLResponse("<h1>Frontend not built</h1>", status_code=500)

# SPA catch-all that WON'T swallow /api/* or /assets/*
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def _spa(full_path: str):
    if full_path.startswith(("api/", "assets/")):
        return HTMLResponse(status_code=404)
    if INDEX_FILE.exists():
        return FileResponse(str(INDEX_FILE))
    return HTMLResponse("<h1>Frontend not built</h1>", status_code=500)

# --------------------------------------------------------

# singleton
@app.on_event("startup")
async def _startup():
    # Do NOT auto-load a model at startup; load on demand via /api/models/load
    asyncio.create_task(start_worker(), name="retitle_worker")

    # Start non-blocking system poller and keep a handle so we can cancel/await it
    t = asyncio.create_task(poll_system_snapshot(1.0), name="system_snapshot_poller")
    app.state.bg_tasks.append(t)

    log.info("🟡 Model will be loaded on-demand (via /api/models/load)")

@app.on_event("shutdown")
async def _shutdown():
    # 1) Cancel and await background tasks so they don't touch a torn-down executor
    tasks = getattr(app.state, "bg_tasks", [])
    for t in tasks:
        try:
            t.cancel()
        except Exception:
            pass
    if tasks:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass

    # 2) Ensure any spawned model workers are terminated to free VRAM/ports
    try:
        n = await supervisor.stop_all()
        log.info("[workers] shutdown: stopped %s worker(s)", n)
    except Exception as e:
        log.warning("[workers] shutdown stop_all error: %r", e)

@app.middleware("http")
async def _capture_auth_headers(request: Request, call_next):
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        request_ctx.set_id_token(auth.split(None, 1)[1])
    else:
        request_ctx.set_id_token("")
    request_ctx.set_x_id((request.headers.get("x-id") or "").strip())
    return await call_next(request)
