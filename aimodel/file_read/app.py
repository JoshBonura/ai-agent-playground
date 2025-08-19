from __future__ import annotations
import os, asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .paths import bootstrap
from .api.health import router as health_router
from .api.models import router as models_router
from .api.chats import router as chats_router
from .api.generate import router as generate_router, is_active  # <-- import is_active
from .store import process_all_pending                           # <-- import pending worker

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

# background worker to apply queued ops for idle sessions
@app.on_event("startup")
async def _pending_worker():
    async def worker():
        # one immediate pass
        try:
            process_all_pending(is_active)
        except Exception:
            pass
        # then loop
        while True:
            try:
                process_all_pending(is_active)
            except Exception:
                pass
            await asyncio.sleep(2.0)  # gentle cadence
    asyncio.create_task(worker())
