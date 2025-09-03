from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import faiss, json, os, time, hashlib
import numpy as np
from ..store.base import APP_DIR   
import shutil

BASE = APP_DIR / "rag"

def _ns_dir(session_id: Optional[str]) -> Path:
    if session_id:
        return BASE / "by_session" / session_id
    return BASE / "global"

def _paths(session_id: Optional[str]) -> Tuple[Path, Path]:
    d = _ns_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "index.faiss", d / "meta.jsonl"

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

def add_vectors(session_id: Optional[str], embeds: np.ndarray, metas: List[Dict], dim: int):
    idx_path, meta_path = _paths(session_id)
    idx = _load_index(dim, idx_path)

    # ensure index type
    if not isinstance(idx, faiss.IndexFlatIP):
        idx = faiss.IndexFlatIP(dim) if idx.ntotal == 0 else idx

    # normalize vectors
    embeds = _norm(embeds)

    # ✅ read existing ids to avoid duplicates
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

def search_vectors(session_id: Optional[str], query_vec: np.ndarray, topk: int, dim: int) -> List[Dict]:
    idx_path, meta_path = _paths(session_id)
    if not idx_path.exists() or not meta_path.exists():
        return []

    idx = _load_index(dim, idx_path)

    # ✅ ensure numpy array for reshape
    query_vec = np.asarray(query_vec, dtype="float32")
    q = _norm(query_vec.reshape(1, -1))

    D, I = idx.search(q, topk)
    out: List[Dict] = []
    rows: Dict[int, Dict] = {}
    with meta_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
                rows[int(j["row"])] = j
            except:
                pass
    for score, row in zip(D[0].tolist(), I[0].tolist()):
        if row < 0:
            continue
        m = rows.get(row)
        if not m:
            continue
        m = dict(m)
        m["score"] = float(score)
        out.append(m)
    return out

def search_similar(qvec: List[float] | np.ndarray, *, k: int = 5, session_id: Optional[str] = None) -> List[Dict]:
    """
    Compatibility wrapper used by retrieve.py.
    qvec: a single embedding vector (list or np.ndarray)
    """
    arr = np.asarray(qvec, dtype="float32")
    dim = int(arr.shape[-1])
    return search_vectors(session_id, arr, k, dim)

def add_texts(
    texts: List[str],
    metas: List[Dict],
    *,
    session_id: Optional[str],
    embed_fn,  # callable: List[str] -> np.ndarray[float32]
) -> int:
    if not texts:
        return 0
    vecs = embed_fn(texts)  # should return (n, d) float32
    if not isinstance(vecs, np.ndarray):
        vecs = np.asarray(vecs, dtype="float32")
    dim = int(vecs.shape[-1])
    add_vectors(session_id, vecs, metas, dim)
    return len(texts)

def delete_namespace(session_id: str) -> bool:
    """
    Hard-delete all RAG data for a given session: the by_session/<sessionId> folder.
    Returns True if it existed and was removed.
    """
    d = _ns_dir(session_id)
    try:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False
    except Exception:
        return False

# --- add near the other helpers ---
def session_has_any_vectors(session_id: Optional[str]) -> bool:
    """
    Return True if this session has any indexed vectors stored on disk.
    We consider the namespace non-empty if the FAISS index exists and ntotal > 0,
    and the meta.jsonl exists with at least one line.
    """
    if not session_id:
        return False

    idx_path, meta_path = _paths(session_id)
    if not idx_path.exists() or not meta_path.exists():
        return False

    try:
        idx = _load_index(dim=1, p=idx_path)  # dim not used by IndexFlatIP reader
        if getattr(idx, "ntotal", 0) <= 0:
            return False
    except Exception as e:
        print(f"[RAG STORE] failed to read index for {session_id}: {e}")
        return False

    try:
        # quick check: meta file has at least one JSONL line
        with meta_path.open("r", encoding="utf-8") as f:
            for _ in f:
                return True
        return False
    except Exception as e:
        print(f"[RAG STORE] failed to read meta for {session_id}: {e}")
        return False
