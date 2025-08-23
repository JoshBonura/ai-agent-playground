from __future__ import annotations
import asyncio
from typing import Tuple, List
import httpx
import trafilatura

HEADERS = {"User-Agent": "LocalAI/0.1 (+clean-fetch)"}

async def fetch_clean(url: str, timeout_s: float = 8.0, max_chars: int = 3000) -> Tuple[str, int, str]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_s) as client:
        r = await client.get(url, headers=HEADERS)
        r.raise_for_status()
        # trafilatura extracts readable article text (Apache-2.0)
        txt = trafilatura.extract(r.text, url=str(r.url)) or ""
        if not txt:
            # fallback: raw text up to cap
            txt = r.text
        txt = txt.strip().replace("\r", "")
        if len(txt) > max_chars:
            txt = txt[:max_chars]
        return (str(r.url), r.status_code, txt)

async def fetch_many(urls: List[str], per_timeout_s: float = 8.0, cap_chars: int = 3000, max_parallel: int = 3):
    sem = asyncio.Semaphore(max_parallel)
    async def _one(u: str):
        async with sem:
            try:
                return u, await fetch_clean(u, per_timeout_s, cap_chars)
            except Exception:
                return u, None
    tasks = [_one(u) for u in urls]
    return await asyncio.gather(*tasks)
