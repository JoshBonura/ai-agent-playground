# store/migrate.py
import json

from .base import APP_DIR, atomic_write_encrypted, index_path, user_root


def migrate_legacy_to_user(uid: str, email: str):
    legacy_idx = APP_DIR / "index.json"
    legacy_chats = APP_DIR / "chats"
    if not legacy_idx.exists() and not legacy_chats.exists():
        return

    root = user_root(uid)
    # migrate index
    if legacy_idx.exists() and not index_path(root).exists():
        try:
            rows = json.loads(legacy_idx.read_text("utf-8"))
            for r in rows:
                r["ownerUid"] = uid
                r["ownerEmail"] = email
            atomic_write_encrypted(uid, root, index_path(root), rows)
            legacy_idx.unlink(missing_ok=True)
        except Exception:
            pass

    # migrate chats
    if legacy_chats.exists():
        for p in legacy_chats.glob("*.json"):
            try:
                data = json.loads(p.read_text("utf-8"))
                data["ownerUid"] = uid
                atomic_write_encrypted(uid, root, (root / "chats" / p.name), data)
                p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            legacy_chats.rmdir()
        except Exception:
            pass
