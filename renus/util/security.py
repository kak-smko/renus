"""Password hashing helpers implemented with Python's standard library.

Passwords are hashed with PBKDF2-HMAC-SHA256.  Each hash receives its own
cryptographically random salt, which is stored alongside the digest in this
self-contained format::

    <urlsafe-salt>$<urlsafe-digest>

The salt is an implementation detail: callers never provide or manage it.
It must remain part of the stored record because removing unique salts makes
identical passwords identifiable and weakens resistance to offline attacks.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from hashlib import pbkdf2_hmac

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
_SALT_BYTES = 16
_DIGEST_BYTES = 32
_MIN_ITERATIONS = 100_000
_MAX_ITERATIONS = 10_000_000
_B64_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _require_text(value: object, name: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value.encode("utf-8")


def _encode_token(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_token(value: object) -> bytes:
    if not isinstance(value, str) or not _B64_TOKEN_RE.fullmatch(value):
        raise ValueError("invalid base64 token")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 token") from exc
    if _encode_token(decoded) != value:
        raise ValueError("non-canonical base64 token")
    return decoded


def _derive(password: object, salt: bytes, iterations: int) -> bytes:
    return pbkdf2_hmac(
        "sha256",
        _require_text(password, "password"),
        salt,
        iterations,
        dklen=_DIGEST_BYTES,
    )


def hash_new_password(password: str) -> str:
    """Hash ``password`` with a random per-password salt.

    The returned value is self-contained and can be stored directly in a
    database.  Hashing the same password twice intentionally produces two
    different values because each call generates a fresh salt.

    Raises
    ------
    TypeError
        If ``password`` is not a string.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, DEFAULT_ITERATIONS)
    return "$".join((_encode_token(salt), _encode_token(digest)))


def _parse_password_hash(value: object) -> tuple[int, bytes, bytes] | None:
    if not isinstance(value, str):
        return None
    parts = value.split("$")
    if len(parts) != 2:
        return None
    try:
        salt = _decode_token(parts[0])
        digest = _decode_token(parts[1])
    except (TypeError, ValueError, OverflowError):
        return None
    if len(salt) != _SALT_BYTES or len(digest) != _DIGEST_BYTES:
        return None
    return DEFAULT_ITERATIONS, salt, digest


def is_correct_password(pw_hash: object, password: object) -> bool:
    """Return whether ``password`` matches a stored password hash.

    Malformed, unsupported, or tampered hashes return ``False``.  Comparison
    of the derived digest is constant-time.
    """
    if not isinstance(password, str):
        return False
    parsed = _parse_password_hash(pw_hash)
    if parsed is None:
        return False

    iterations, salt, stored_digest = parsed
    candidate = _derive(password, salt, iterations)
    return secrets.compare_digest(candidate, stored_digest)
