"""Symmetric encryption for secrets stored at rest (currently: project SMTP
passwords). Keyed from SECRET_KEY -- rotating that key makes previously
encrypted values undecryptable, same as it already invalidates JWTs.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Best-effort decrypt. Returns "" for empty/foreign/corrupt input rather
    than raising, since callers treat a missing password the same as one that
    can no longer be recovered (e.g. after a SECRET_KEY rotation)."""
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ""
