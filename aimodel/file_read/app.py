from __future__ import annotations
import os, asyncio
from pathlib import Path

try:
    from dotenv import load_dotenv
    _ENV_PATH = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
except Exception as _e:
    print(f"[env] NOTE: could not load .env: {_e}")

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware

from .core import request_ctx
from .adaptive.config.paths import bootstrap
from .workers.retitle_worker import start_worker
from .runtime.model_runtime import load_model

from .api.models import router as models_router
from .api.chats import router as chats_router
from .api.generate_router import router as generate_router
from .api.metrics import router as metrics_router
from .api.rag import router as rag_router
from .api import settings as settings_router
from .api.billing import router as billing_router
from .api.licensing_router import router as licensing_router
from .api.auth_router import router as auth_router, require_auth

bootstrap()
app = FastAPI()

# --- CORS setup ---
origins = [
    o.strip()
    for o in os.getenv("APP_CORS_ORIGIN", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
deps = [Depends(require_auth)]

# Public
app.include_router(models_router)

# Protected
app.include_router(chats_router,           dependencies=deps)
app.include_router(generate_router,        dependencies=deps)
app.include_router(settings_router.router, dependencies=deps)
app.include_router(rag_router,             dependencies=deps)
app.include_router(metrics_router,         dependencies=deps)
app.include_router(billing_router,         dependencies=deps)
app.include_router(licensing_router,       dependencies=deps)

# Auth endpoints (login/logout/me)
app.include_router(auth_router)

# --- Startup tasks ---
@app.on_event("startup")
async def _startup():
    try:
        load_model(config_patch={})
        print("✅ llama model loaded at startup")
    except Exception as e:
        print(f"❌ llama failed to load at startup: {e}")
    asyncio.create_task(start_worker(), name="retitle_worker")

# --- Per-request header capture ---
@app.middleware("http")
async def _capture_auth_headers(request: Request, call_next):
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        request_ctx.set_id_token(auth.split(None, 1)[1])
    else:
        request_ctx.set_id_token("")
    request_ctx.set_x_id((request.headers.get("x-id") or "").strip())
    return await call_next(request)
