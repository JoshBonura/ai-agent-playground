from __future__ import annotations
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List, Optional
from ..web.duckduckgo import DuckDuckGoProvider
from ..web.fetch import fetch_clean
from fastapi.responses import JSONResponse
router = APIRouter()

class WebResult(BaseModel):
    title: str
    url: str
    snippet: Optional[str] = None
    rank: int


# ...
@router.get("/api/search", response_model=List[WebResult])
async def api_search(q: str = Query(..., min_length=2), k: int = 3):
    try:
        prov = DuckDuckGoProvider()
        hits = await prov.search(q, k=k)
        if not hits:
            return JSONResponse({"error": "No results (search may be blocked or rate-limited)."}, status_code=502)
        return [WebResult(title=h.title, url=h.url, snippet=h.snippet, rank=h.rank) for h in hits]
    except Exception as e:
        return JSONResponse({"error": f"search failed: {e}"}, status_code=500)


@router.get("/api/fetch")
async def api_fetch(url: str):
    final_url, status, text = await fetch_clean(url)
    return {"url": final_url, "status": status, "preview": text[:2000]}
