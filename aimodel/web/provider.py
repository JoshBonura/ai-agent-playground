from __future__ import annotations

from dataclasses import dataclass

from ..core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str | None = None
    rank: int = 0


class SearchProvider:
    async def search(self, query: str, k: int = 3) -> list[SearchHit]:
        raise NotImplementedError
