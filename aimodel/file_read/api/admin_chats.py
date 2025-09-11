from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps.admin_deps import require_admin
from ..store import chats as store
from ..store.base import APP_DIR, user_root

router = APIRouter(prefix="/api/admins/chats", tags=["admins"])


def _users_dir() -> Path:
    # Assumes per-user data lives under APP_DIR/users/<uid> (same convention as user_root)
    return APP_DIR / "users"


def _list_all_uids() -> list[str]:
    try:
        d = _users_dir()
        if not d.exists():
            return []
        return sorted([p.name for p in d.iterdir() if p.is_dir()])
    except Exception:
        return []


# ---------- Admin: only my chats (convenience wrapper) ----------
@router.get("/mine/paged")
def admin_list_mine_paged(
    page: int = 0,
    size: int = 30,
    ceiling: str | None = None,
    user=Depends(require_admin),
):
    uid = user.get("user_id") or user.get("sub")
    root = user_root(uid)
    rows, total, total_pages, last_flag = store.list_paged(root, uid, page, size, ceiling)
    content = [
        {
            **asdict(r),
            "ownerUid": uid,  # include owner for frontend clarity
            "ownerEmail": (user.get("email") or "").lower(),
        }
        for r in rows
    ]
    return {
        "content": content,
        "totalElements": total,
        "totalPages": total_pages,
        "size": size,
        "number": page,
        "first": (page == 0),
        "last": last_flag,
        "empty": len(content) == 0,
    }


# ---------- Admin: all users’ chats (default view) ----------
@router.get("/all/paged")
def admin_list_all_paged(
    page: int = 0,
    size: int = 30,
    ceiling: str | None = None,
    _user=Depends(require_admin),
):
    # Aggregate per-user indexes, sort by updatedAt desc, then paginate globally
    aggregate: list[dict[str, Any]] = []

    for uid in _list_all_uids():
        try:
            root = user_root(uid)
            rows, _total, _tp, _last = store.list_paged(
                root, uid, 0, 10_000, ceiling
            )  # big page to collect all
            for r in rows:
                d = asdict(r)
                # enrich with owner for cross-user listing
                d["ownerUid"] = uid
                # ownerEmail is not available from index safely here; omit or fill if you keep it in index
                aggregate.append(d)
        except Exception:
            # best-effort; skip bad/empty users
            continue

    # Sort globally
    aggregate.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)

    # Global pagination
    page = max(0, int(page))
    size = max(1, int(size))
    start = page * size
    end = start + size
    page_items = aggregate[start:end]
    total = len(aggregate)
    total_pages = (total + size - 1) // size if total else 1
    last_flag = end >= total

    return {
        "content": page_items,
        "totalElements": total,
        "totalPages": total_pages,
        "size": size,
        "number": page,
        "first": (page == 0),
        "last": last_flag,
        "empty": len(page_items) == 0,
    }


# ---------- Admin: read messages of a specific user’s chat ----------
@router.get("/{target_uid}/{session_id}/messages")
def admin_list_messages(target_uid: str, session_id: str, _user=Depends(require_admin)):
    root = user_root(target_uid)
    try:
        rows = store.list_messages(root, target_uid, session_id)
    except Exception as e:
        raise HTTPException(404, f"Chat not found: {e}") from e
    return [asdict(r) for r in rows]
