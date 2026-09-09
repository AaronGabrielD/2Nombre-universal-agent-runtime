"""Provider-neutral local authentication helpers for the Chainlit UI."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets


DEFAULT_PBKDF2_ITERATIONS = 600_000


class UIAuthConfigError(ValueError):
    """Raised when local UI authentication configuration is malformed."""


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> str:
    """Return a self-contained PBKDF2-SHA256 password record."""
    if not isinstance(password, str) or not password:
        raise UIAuthConfigError("password cannot be empty")
    if iterations < 100_000:
        raise UIAuthConfigError("PBKDF2 iterations are too low")
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt_bytes).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password record without exposing whether parsing or matching failed."""
    try:
        scheme, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        if iterations < 100_000:
            return False
        salt = _decode(raw_salt)
        expected = _decode(raw_digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def authenticate_from_environment(username: str, password: str):
    """Return a Chainlit User-compatible dictionary or None for failed auth.

    The function intentionally returns plain data so it can be unit-tested without
    importing Chainlit. The Chainlit callback wraps the result in ``cl.User``.
    """
    configured_username = os.getenv("UAR_AUTH_USERNAME", "").strip()
    encoded_password = os.getenv("UAR_AUTH_PASSWORD_HASH", "").strip()
    if not configured_username or not encoded_password:
        return None
    if not hmac.compare_digest(username.strip(), configured_username):
        return None
    if not verify_password(password, encoded_password):
        return None
    return {
        "identifier": configured_username,
        "metadata": {"role": os.getenv("UAR_AUTH_ROLE", "user").strip() or "user", "provider": "password"},
    }


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
