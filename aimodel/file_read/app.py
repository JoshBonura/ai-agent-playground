# aimodel/file_read/app.py
from __future__ import annotations
import os, asyncio, atexit
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .paths import bootstrap
from .retitle_worker import start_worker
from .api.health import router as health_router
from .api.models import router as models_router
from .api.chats import router as chats_router
from .store import process_all_pending
from .model_runtime import load_model
from .api.search import router as search_router
from .api.generate_router import router as generate_router
from .services.cancel import is_active

bootstrap()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("APP_CORS_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(models_router)
app.include_router(chats_router)
app.include_router(generate_router)
app.include_router(search_router)

@app.on_event("startup")
async def _startup():
    try:
        load_model(config_patch={})
        print("✅ llama model loaded at startup")
    except Exception as e:
        print(f"❌ llama failed to load at startup: {e}")

    async def worker():
        while True:
            try:
                await asyncio.to_thread(process_all_pending, is_active)
            except Exception:
                pass
            await asyncio.sleep(2.0)

    asyncio.create_task(worker(), name="pending_worker")
    asyncio.create_task(start_worker(), name="retitle_worker")
