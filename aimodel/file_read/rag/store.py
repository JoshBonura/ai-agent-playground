from __future__ import annotations

import logging

log = logging.getLogger(__name__)
import json
import shutil
from pathlib import Path

import faiss
import numpy as np

from ..core.logging import get_logger
from ..store.base import APP_DIR

log = get_logger(__name__)

BASE = APP_DIR / "rag"


def _ns_dir(session_id: str | None) -> Path:
    if session_id:
        return BASE / "by_session" / session_id
    return BASE / "global"


def _paths(session_id: str | None) -> tuple[Path, Path]:
    d = _ns_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return (d / "index.faiss", d / "meta.jsonl")


def _norm(x: np.ndarray) -> np.ndarray:
    x = x.astype("float32")
    faiss.normalize_L2(x)
    return x


def _load_index(dim: int, p: Path) -> faiss.Index:
    if p.exists():
        return faiss.read_index(str(p))
    return faiss.IndexFlatIP(dim)


def _save_index(idx: faiss.Index, p: Path) -> None:
    faiss.write_index(idx, str(p))


def add_vectors(session_id: str | None, embeds: np.ndarray, metas: list[dict], dim: int):
    idx_path, meta_path = _paths(session_id)
    idx = _load_index(dim, idx_path)
    if not isinstance(idx, faiss.IndexFlatIP):
        idx = faiss.IndexFlatIP(dim) if idx.ntotal == 0 else idx
    embeds = _norm(embeds)
    existing_ids = set()
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                    existing_ids.add(j["id"])
                except:
                    pass
    start = idx.ntotal
    new_embeds = []
    new_metas = []
    for i, m in enumerate(metas):
        if m["id"] in existing_ids:
            continue
        m["row"] = start + len(new_embeds)
        new_embeds.append(embeds[i])
        new_metas.append(m)
    if new_embeds:
        idx.add(np.vstack(new_embeds))
        _save_index(idx, idx_path)
        with meta_path.open("a", encoding="utf-8") as f:
            for m in new_metas:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")


def search_vectors(
    session_id: str | None, query_vec: np.ndarray, topk: int, dim: int
) -> list[dict]:
    idx_path, meta_path = _paths(session_id)
    if not idx_path.exists() or not meta_path.exists():
        return []
    idx = _load_index(dim, idx_path)
    query_vec = np.asarray(query_vec, dtype="float32")
    q = _norm(query_vec.reshape(1, -1))
    D, I = idx.search(q, topk)
    out: list[dict] = []
    rows: dict[int, dict] = {}
    with meta_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
                rows[int(j["row"])] = j
            except:
                pass
    for score, row in zip(D[0].tolist(), I[0].tolist(), strict=False):
        if row < 0:
            continue
        m = rows.get(row)
        if not m:
            continue
        m = dict(m)
        m["score"] = float(score)
        out.append(m)
    return out


def search_similar(
    qvec: list[float] | np.ndarray, *, k: int = 5, session_id: str | None = None
) -> list[dict]:
    """
    Compatibility wrapper used by retrieve.py.
    qvec: a single embedding vector (list or np.ndarray)
    """
    arr = np.asarray(qvec, dtype="float32")
    dim = int(arr.shape[-1])
    return search_vectors(session_id, arr, k, dim)


def add_texts(texts: list[str], metas: list[dict], *, session_id: str | None, embed_fn) -> int:
    if not texts:
        return 0
    vecs = embed_fn(texts)
    if not isinstance(vecs, np.ndarray):
        vecs = np.asarray(vecs, dtype="float32")
    dim = int(vecs.shape[-1])
    add_vectors(session_id, vecs, metas, dim)
    return len(texts)


def delete_namespace(session_id: str) -> bool:
    d = _ns_dir(session_id)
    try:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False
    except Exception:
        return False


def session_has_any_vectors(session_id: str | None) -> bool:
    if not session_id:
        return False
    idx_path, meta_path = _paths(session_id)
    if not idx_path.exists() or not meta_path.exists():
        return False
    try:
        idx = _load_index(dim=1, p=idx_path)
        if getattr(idx, "ntotal", 0) <= 0:
            return False
    except Exception as e:
        log.error(f"[RAG STORE] failed to read index for {session_id}: {e}")
        return False
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            for _ in f:
                return True
        return False
    except Exception as e:
        log.error(f"[RAG STORE] failed to read meta for {session_id}: {e}")
        return False
