from __future__ import annotations
from typing import List, Dict, Optional
import numpy as np
from .store import search_vectors

def reciprocal_rank_fusion(results: List[List[Dict]], k: int = 60) -> List[Dict]:
    # results = [list_from_chat, list_from_global]
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

def merge_chat_first(chat_hits: List[Dict], global_hits: List[Dict], alpha: float = 0.5) -> List[Dict]:
    # alpha weights semantic scores; RRF stabilizes positions
    fused = reciprocal_rank_fusion([chat_hits, global_hits])
    return fused
