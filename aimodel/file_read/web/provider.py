from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SearchHit:
    title: str
    url: str
    snippet: Optional[str] = None
    rank: int = 0

class SearchProvider:
    async def search(self, query: str, k: int = 3) -> List[SearchHit]:
        raise NotImplementedError
