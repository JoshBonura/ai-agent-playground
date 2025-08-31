from __future__ import annotations
import os, asyncio, atexit
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .adaptive.config.paths import bootstrap
from .workers.retitle_worker import start_worker
from .api.models import router as models_router
from .api.chats import router as chats_router
from .runtime.model_runtime import load_model
from .api.generate_router import router as generate_router
from .api import metrics as metrics_api
from .api.rag import router as rag_router
from .services.cancel import is_active
from .api import settings as settings_router
from .core.settings import SETTINGS
from .services.warmup import start_warmup_runner, stop_warmup_runner, warmup_once

bootstrap()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("APP_CORS_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models_router)
app.include_router(chats_router)
app.include_router(generate_router)
app.include_router(settings_router.router)
app.include_router(rag_router)
app.include_router(metrics_api.router)

_warmup_stop_ev = None

@app.on_event("startup")
async def _startup():
    try:
        load_model(config_patch={})
        print("✅ llama model loaded at startup")
    except Exception as e:
        print(f"❌ llama failed to load at startup: {e}")

    if bool(SETTINGS.get("warmup_enabled", True)) and bool(SETTINGS.get("warmup_on_start", True)):
        try:
            await warmup_once()
            print("✅ warmup_on_start complete")
        except Exception as e:
            print(f"⚠️ warmup_on_start failed: {e}")

    global _warmup_stop_ev
    _warmup_stop_ev = start_warmup_runner(asyncio.get_event_loop())

    asyncio.create_task(start_worker(), name="retitle_worker")

@app.on_event("shutdown")
async def _shutdown():
    stop_warmup_runner(_warmup_stop_ev)
