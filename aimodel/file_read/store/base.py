from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..adaptive.config.paths import app_data_dir
from ..core.crypto_keys import get_user_dek
from ..core.logging import get_logger

log = get_logger(__name__)

APP_DIR = app_data_dir()
USERS_DIR = APP_DIR / "users"


def user_root(uid: str) -> Path:
    r = USERS_DIR / uid
    (r / "chats").mkdir(parents=True, exist_ok=True)
    return r


def index_path(root: Path) -> Path:
    return root / "index.json"


def chats_dir(root: Path) -> Path:
    d = root / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def chat_path(root: Path, session_id: str) -> Path:
    return chats_dir(root) / f"{session_id}.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _encrypt_bytes(uid: str, relpath: str, plaintext: bytes) -> bytes:
    key = get_user_dek(uid)  # 32 bytes
    aes = AESGCM(key)
    nonce = secrets.token_bytes(12)
    aad_obj = {"uid": uid, "path": relpath}
    aad = json.dumps(aad_obj, ensure_ascii=False).encode("utf-8")
    ct = aes.encrypt(nonce, plaintext, aad)
    wrapper = {
        "v": 1,
        "alg": "aes-256-gcm",
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "aad": base64.b64encode(aad).decode("utf-8"),
        "ct": base64.b64encode(ct).decode("utf-8"),
    }
    return json.dumps(wrapper, ensure_ascii=False).encode("utf-8")


def _decrypt_bytes(uid: str, relpath: str, blob: bytes) -> bytes:
    obj = json.loads(blob.decode("utf-8"))
    aes = AESGCM(get_user_dek(uid))
    nonce = base64.b64decode(obj["nonce"])
    aad = base64.b64decode(obj["aad"])
    expected = json.dumps({"uid": uid, "path": relpath}, ensure_ascii=False).encode("utf-8")
    if aad != expected:
        raise ValueError("AAD mismatch")
    ct = base64.b64decode(obj["ct"])
    return aes.decrypt(nonce, ct, aad)


def write_json_encrypted_org(root: Path, path: Path, data):
    # ensure folder exists
    path.parent.mkdir(parents=True, exist_ok=True)
    # use a stable org DEK (e.g., keyring entry for uid="org")
    atomic_write_encrypted("org", root, path, data)


def read_json_encrypted_org(root: Path, path: Path):
    return read_json_encrypted("org", root, path)


def atomic_write_encrypted(uid: str, root: Path, path: Path, data: dict[str, Any] | list[Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    rel = str(path.relative_to(root))
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    blob = _encrypt_bytes(uid, rel, plaintext)

    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        shutil.move(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def read_json_encrypted(uid: str, root: Path, path: Path) -> Any:
    with path.open("rb") as f:
        blob = f.read()
    rel = str(path.relative_to(root))
    plain = _decrypt_bytes(uid, rel, blob)
    return json.loads(plain.decode("utf-8"))


__all__ = [
    "APP_DIR",
    "USERS_DIR",
    "atomic_write_encrypted",
    "chat_path",
    "chats_dir",
    "index_path",
    "now_iso",
    "read_json_encrypted",
    "user_root",
]
