"""Signed bearer tokens.

A compact JWT-shaped token signed with HMAC-SHA256:

    base64url(payload_json).base64url(signature)

Hand-rolling *signing* is low risk (one `hmac.new` plus a constant-time compare,
the same construction Django's signing module uses); hand-rolling a cipher would
not be, and we don't. Using this instead of PyJWT keeps the dependency list
unchanged, which matters because none of this project's pinned deps are installed
in a way that lets a new compiled wheel be verified.

The signing secret comes from AUTH_SECRET. If it is unset we generate a random
one at import time: tokens then stop working across restarts, which is a safe
failure (everyone is logged out) rather than an exploitable one (a shipped
default secret would let anyone forge a token for any account).
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import secrets
import time
from hashlib import sha256

logger = logging.getLogger("auth.tokens")

DEFAULT_TTL_SECONDS = 12 * 60 * 60  # 12 hours
_ALGORITHM = "HS256"

_EPHEMERAL_SECRET = False


def _load_secret() -> bytes:
    global _EPHEMERAL_SECRET
    raw = (os.getenv("AUTH_SECRET") or "").strip()
    if raw:
        if len(raw) < 32:
            logger.warning(
                "AUTH_SECRET is shorter than 32 characters; use a longer random "
                "value (e.g. `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`)."
            )
        return raw.encode("utf-8")
    _EPHEMERAL_SECRET = True
    logger.warning(
        "AUTH_SECRET is not set — generating a random per-process secret. "
        "All sessions will be invalidated on restart and tokens will not work "
        "across multiple workers. Set AUTH_SECRET in production."
    )
    return secrets.token_bytes(48)


_SECRET = _load_secret()


def using_ephemeral_secret() -> bool:
    """True when no AUTH_SECRET was configured (surfaced via /capabilities)."""
    return _EPHEMERAL_SECRET


class TokenError(Exception):
    """Raised when a token is malformed, tampered with, or expired."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload_b64: str) -> str:
    return _b64e(hmac.new(_SECRET, payload_b64.encode("ascii"), sha256).digest())


def create_access_token(
    user_id: str, *, email: str = "", ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)`` for ``user_id``."""
    if not user_id:
        raise ValueError("user_id is required to mint a token.")
    now = int(time.time())
    expires_at = now + int(ttl_seconds)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": expires_at,
        "alg": _ALGORITHM,
        # Makes otherwise-identical tokens distinct, so one can be revoked
        # by jti later without touching the rest.
        "jti": secrets.token_urlsafe(8),
    }
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}", expires_at


def decode_access_token(token: str) -> dict:
    """Verify a token and return its payload.

    The signature is checked *before* the payload is parsed, so unverified
    attacker-controlled JSON never reaches any decision.
    """
    if not token or not isinstance(token, str):
        raise TokenError("Missing token.")
    parts = token.split(".")
    if len(parts) != 2:
        raise TokenError("Malformed token.")
    payload_b64, signature = parts
    if not hmac.compare_digest(_sign(payload_b64), signature):
        raise TokenError("Invalid token signature.")

    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
        raise TokenError("Malformed token payload.") from None
    if not isinstance(payload, dict):
        raise TokenError("Malformed token payload.")
    # Signed by us, but a token minted under a different algorithm is not one
    # we know how to validate.
    if payload.get("alg") != _ALGORITHM:
        raise TokenError("Unsupported token algorithm.")
    if not payload.get("sub"):
        raise TokenError("Token has no subject.")
    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        raise TokenError("Token has an invalid expiry.") from None
    if expires_at <= int(time.time()):
        raise TokenError("Token has expired.")
    return payload
