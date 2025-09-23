# ext/ai_service.py

from fastapi import FastAPI
from ext.runtime_api import router as runtime_router  # absolute import = reliable

app = FastAPI(title="AI Agent Playground Runtime Service")

# Mount runtime endpoints (/api/runtime/*)
app.include_router(runtime_router)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Optional: simple root for quick sanity checks
@app.get("/")
def root():
    return {"service": "runtime", "ok": True}
