from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from ..core.logging import get_logger

log = get_logger(__name__)
from .store import _ns_dir

_META_FN = "meta.jsonl"
_INDEX_FN = "index.faiss"


def _meta_path_ro(session_id: str | None) -> Path:
    return _ns_dir(session_id) / _META_FN


def _index_path_ro(session_id: str | None) -> Path:
    return _ns_dir(session_id) / _INDEX_FN


def _paths_mut(session_id: str | None) -> tuple[Path, Path]:
    d = _ns_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / _INDEX_FN, d / _META_FN


def _read_meta(meta_path: Path) -> list[dict]:
    if not meta_path.exists():
        return []
    out: list[dict] = []
    with meta_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                if isinstance(j, dict):
                    out.append(j)
            except:
                pass
    return out


def _write_meta(meta_path: Path, rows: list[dict]) -> None:
    tmp = meta_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for j in rows:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    tmp.replace(meta_path)


def _norm(x: np.ndarray) -> np.ndarray:
    x = x.astype("float32")
    faiss.normalize_L2(x)
    return x


def list_sources(session_id: str | None, include_global: bool = True) -> list[dict]:
    def _agg(ns: str | None) -> dict[str, int]:
        mp = _meta_path_ro(ns)
        agg: dict[str, int] = {}
        for j in _read_meta(mp):
            src = (j.get("source") or "").strip()
            if not src:
                continue
            agg[src] = agg.get(src, 0) + 1
        return agg

    rows: list[dict] = []
    # session first
    if session_id is not None:
        for src, n in _agg(session_id).items():
            rows.append({"source": src, "sessionId": session_id, "chunks": n})
    if include_global:
        for src, n in _agg(None).items():
            rows.append({"source": src, "sessionId": None, "chunks": n})
    return rows


def hard_delete_source(source: str, *, session_id: str | None, embedder) -> dict:
    idx_path, meta_path = _paths_mut(session_id)
    rows = _read_meta(meta_path)
    if not rows:
        return {"ok": True, "removed": 0, "remaining": 0}

    keep: list[dict] = []
    removed = 0
    for j in rows:
        if str(j.get("source") or "").strip() == source:
            removed += 1
        else:
            keep.append(j)

    if removed == 0:
        return {"ok": True, "removed": 0, "remaining": len(keep)}

    for i, j in enumerate(keep):
        j["row"] = i

    if len(keep) == 0:
        if idx_path.exists():
            try:
                idx_path.unlink()
            except:
                pass
        _write_meta(meta_path, [])
        return {"ok": True, "removed": removed, "remaining": 0}

    texts = [str(j.get("text") or "") for j in keep]
    B = 128  # batch size
    parts: list[np.ndarray] = []
    for i in range(0, len(texts), B):
        vec = embedder(texts[i : i + B])
        if not isinstance(vec, np.ndarray):
            vec = np.asarray(vec, dtype="float32")
        parts.append(vec.astype("float32"))
    embeds = np.vstack(parts)
    embeds = _norm(embeds)

    dim = int(embeds.shape[-1])
    new_index = faiss.IndexFlatIP(dim)
    new_index.add(embeds)

    faiss.write_index(new_index, str(idx_path))
    _write_meta(meta_path, keep)

    return {"ok": True, "removed": removed, "remaining": len(keep)}
