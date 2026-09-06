"""Password hashing.

PBKDF2-HMAC-SHA256 from the standard library. bcrypt/argon2 would be marginally
stronger per unit of CPU, but both need compiled wheels; PBKDF2 with a high
iteration count is an OWASP-accepted choice and keeps this project dependency-free.

Stored format (single column, self-describing so the cost can be raised later
without invalidating existing passwords):

    pbkdf2_sha256$<iterations>$<salt_b64>$<derived_key_b64>
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
# OWASP's 2023 floor for PBKDF2-HMAC-SHA256.
DEFAULT_ITERATIONS = 600_000
_SALT_BYTES = 16
_KEY_BYTES = 32

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024  # Bound the work an unauthenticated caller can cause.


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=_KEY_BYTES
    )


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return a self-describing hash string for ``password``."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64e(salt)}${_b64e(derived)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored hash.

    Returns False for malformed or unknown-algorithm hashes rather than raising,
    so a corrupt row cannot be used to probe the login endpoint's behaviour.
    """
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt_b64, expected_b64 = stored.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        derived = _derive(password, _b64d(salt_b64), int(iterations))
        return hmac.compare_digest(derived, _b64d(expected_b64))
    except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
        return False


def needs_rehash(stored: str, *, iterations: int = DEFAULT_ITERATIONS) -> bool:
    """True when a stored hash uses a weaker cost than the current default.

    Call after a successful login to transparently upgrade old hashes.
    """
    try:
        algorithm, stored_iterations, _, _ = stored.split("$", 3)
    except (ValueError, AttributeError):
        return True
    return algorithm != ALGORITHM or int(stored_iterations) < iterations


def validate_password_strength(password: str) -> str | None:
    """Return an error message if the password is unacceptable, else None.

    Deliberately minimal: length is the property that actually matters most, and
    aggressive composition rules push people toward predictable substitutions.
    """
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if password.strip() == "":
        return "Password cannot be only whitespace."
    return None
