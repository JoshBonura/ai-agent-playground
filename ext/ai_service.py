# ext/ai_service.py
from __future__ import annotations

from fastapi import FastAPI
from ext.runtime_api import router as runtime_router  # same-origin runtime control

app = FastAPI(title="AI Agent Playground Runtime Service")

# Mount runtime endpoints (/api/runtime/*)
app.include_router(runtime_router)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/")
def root():
    return {"service": "runtime", "ok": True}
