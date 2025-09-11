# core/crypto_keys.py  (new file; minimal)
import base64
import os
import secrets

SERVICE = "LocalMindChats"
KEY_ENV = "LOCALMIND_DEK_BASE64"
ORG_SERVICE = "LocalMindOrg"
ORG_ENV = "LOCALMIND_ORG_DEK_BASE64"  # emergency override


def _from_env():
    v = os.getenv(KEY_ENV, "").strip()
    if v:
        raw = base64.b64decode(v)
        if len(raw) == 32:
            return raw
    return None


def _from_keyring(uid: str):
    try:
        import keyring

        b64 = keyring.get_password(SERVICE, uid)
        if b64:
            raw = base64.b64decode(b64)
            if len(raw) == 32:
                return raw
        # create and save
        raw = secrets.token_bytes(32)
        keyring.set_password(SERVICE, uid, base64.b64encode(raw).decode())
        return raw
    except Exception:
        return None


# Start simple: env → keyring → crash (you can add Argon2 fallback later)
_cache: dict[str, bytes] = {}


def get_user_dek(uid: str) -> bytes:
    if uid in _cache:
        return _cache[uid]
    env = _from_env()
    if env:
        _cache[uid] = env
        return env
    kr = _from_keyring(uid)
    if kr:
        _cache[uid] = kr
        return kr
    raise RuntimeError("No keyring available and no env DEK provided")


def get_org_dek() -> bytes:
    v = os.getenv(ORG_ENV, "").strip()
    if v:
        raw = base64.b64decode(v)
        if len(raw) == 32:
            return raw
    try:
        import keyring

        b64 = keyring.get_password(ORG_SERVICE, "org")
        if b64:
            raw = base64.b64decode(b64)
            if len(raw) == 32:
                return raw
        raw = secrets.token_bytes(32)
        keyring.set_password(ORG_SERVICE, "org", base64.b64encode(raw).decode())
        return raw
    except Exception:
        raise RuntimeError("No org key: set LOCALMIND_ORG_DEK_BASE64 or install keyring")
