from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from starlette.staticfiles import StaticFiles

from .api import admins as admins_api
# 1) Configure logging first, then get a module logger
from .core.logging import get_logger, setup_logging

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
from .api.generate_router import router as generate_router
from .api.licensing_router import router as licensing_router
from .api.metrics import router as metrics_router
from .api.models import router as models_router
from .api.rag import router as rag_router
from .core import request_ctx
from .runtime.model_runtime import load_model
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
app.include_router(admins_api.router, dependencies=deps)
app.include_router(admin_chats_router, dependencies=deps)


# ---------- Serve built frontend (Vite 'dist') ----------
# Adjust the path if your dist lives elsewhere.
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
    try:
        load_model(config_patch={})
        log.info("✅ llama model loaded at startup")
    except Exception as e:
        log.error(f"❌ llama failed to load at startup: {e}")
    asyncio.create_task(start_worker(), name="retitle_worker")


@app.middleware("http")
async def _capture_auth_headers(request: Request, call_next):
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        request_ctx.set_id_token(auth.split(None, 1)[1])
    else:
        request_ctx.set_id_token("")
    request_ctx.set_x_id((request.headers.get("x-id") or "").strip())
    return await call_next(request)
