from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet

from .config import CONFIG


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def future_utc(days: int) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds") + "Z"


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("密码至少需要 8 位。")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return (
        f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def make_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def make_temporary_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(14))


def _fernet() -> Fernet:
    digest = hashlib.sha256(CONFIG.app_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def mask_secret(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"

