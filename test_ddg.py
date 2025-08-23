# test_ddg.py
import asyncio
from urllib.parse import urlparse

from aimodel.file_read.web.duckduckgo import DuckDuckGoProvider, _CACHE  # _CACHE is optional

async def main():
    prov = DuckDuckGoProvider()

    # Optional: bypass the in-memory cache to force a fresh fetch
    _CACHE.clear()

    query = "current date"
    k = 5
    hits = await prov.search(query, k=k)

    print(f"\nTop {len(hits)} results for: {query!r}")
    for i, h in enumerate(hits, 1):
        host = (urlparse(h.url).hostname or "").removeprefix("www.")
        print(f"{i:>2}. [{host}] {h.title}\n    {h.url}")

if __name__ == "__main__":
    asyncio.run(main())
