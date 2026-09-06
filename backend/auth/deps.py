"""FastAPI dependencies for authenticated requests.

`current_user` is the single place identity is decided. Endpoints take the
authenticated user as a parameter and must never accept a user id from the
client — that is exactly the hole this replaces.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from auth.tokens import TokenError, decode_access_token
from db import database

# Deliberately permissive: enough to reject obvious junk without rejecting
# valid-but-unusual addresses. Real verification means sending mail.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    email = normalize_email(email)
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _UNAUTHENTICATED
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _UNAUTHENTICATED
    return token.strip()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Resolve the caller from the Authorization header.

    Returns the user row (without the password hash). Raises 401 for a missing,
    malformed, tampered, or expired token, and also when the token is valid but
    the account no longer exists — otherwise a deleted user's outstanding tokens
    would keep working until they expired.
    """
    token = _bearer_token(authorization)
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = database.get_user_by_user_id(str(payload["sub"]))
    if user is None:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


def current_user_id(user: CurrentUser) -> str:
    """Just the opaque user id, for endpoints that need nothing else."""
    return user["user_id"]


CurrentUserId = Annotated[str, Depends(current_user_id)]
