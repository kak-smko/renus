from __future__ import annotations

import secrets
from hashlib import sha3_512

DEFAULT_SALT = "renus"

__all__ = ["DEFAULT_SALT", "hash_new_password", "is_correct_password"]

def _derive(password: str, salt: str) -> str:
    p = password.encode("utf-8")
    s = salt.encode("utf-8")
    inner = sha3_512(s + p).digest()
    return sha3_512(p + inner).hexdigest()

def hash_new_password(password: str, salt: str = DEFAULT_SALT) -> str:
    """Derive and return a salted hash for a password.

    Parameters
    ----------
    password:
        Plaintext password to hash.
    salt:
        Salt value mixed into the hash. Defaults to ``DEFAULT_SALT``.
    """
    return _derive(password, salt)

def is_correct_password(pw_hash: str, password: str, salt: str = DEFAULT_SALT) -> bool:
    """Verify a password against a stored hash using constant-time comparison.

    Parameters
    ----------
    pw_hash:
        Previously generated password hash to compare against.
    password:
        Plaintext password to verify.
    salt:
        Salt used when the hash was derived. Defaults to ``DEFAULT_SALT``.
    """
    return secrets.compare_digest(_derive(password, salt), pw_hash)
