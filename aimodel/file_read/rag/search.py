from __future__ import annotations
from typing import List, Dict

def reciprocal_rank_fusion(results: List[List[Dict]], k: int = 60) -> List[Dict]:
    scores: Dict[str, float] = {}
    lookup: Dict[str, Dict] = {}
    for lst in results:
        for rank, r in enumerate(lst, start=1):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            lookup[rid] = r
    fused = [{"score": s, **lookup[rid]} for rid, s in scores.items()]
    fused.sort(key=lambda x: x["score"], reverse=True)
    return fused
