from __future__ import annotations

from ..core.logging import get_logger

log = get_logger(__name__)


def reciprocal_rank_fusion(results: list[list[dict]], k: int = 60) -> list[dict]:
    scores: dict[str, float] = {}
    lookup: dict[str, dict] = {}
    for lst in results:
        for rank, r in enumerate(lst, start=1):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            lookup[rid] = r
    fused = [{"score": s, **lookup[rid]} for rid, s in scores.items()]
    fused.sort(key=lambda x: x["score"], reverse=True)
    return fused
