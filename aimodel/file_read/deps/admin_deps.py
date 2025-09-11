# aimodel/file_read/deps/admin_deps.py
from __future__ import annotations

from fastapi import Depends, HTTPException

from ..core import admins as reg
from .auth_deps import require_auth


async def require_admin(user=Depends(require_auth)):
    uid = user.get("user_id") or user.get("sub")
    if uid and reg.is_admin(uid):
        return user
    raise HTTPException(403, "Admin required")
