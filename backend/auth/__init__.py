"""Authentication: password hashing, signed bearer tokens, request identity.

Public surface:

    hash_password / verify_password / needs_rehash / validate_password_strength
    create_access_token / decode_access_token / TokenError
    current_user / current_user_id  (FastAPI dependencies)
    login_limiter / register_limiter
"""
from __future__ import annotations

from auth.ratelimit import RateLimiter, login_limiter, register_limiter
from auth.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from auth.tokens import (
    DEFAULT_TTL_SECONDS,
    TokenError,
    create_access_token,
    decode_access_token,
    using_ephemeral_secret,
)

__all__ = [
    "MIN_PASSWORD_LENGTH",
    "DEFAULT_TTL_SECONDS",
    "RateLimiter",
    "TokenError",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "login_limiter",
    "needs_rehash",
    "register_limiter",
    "using_ephemeral_secret",
    "validate_password_strength",
    "verify_password",
]
