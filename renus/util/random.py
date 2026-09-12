from __future__ import annotations

import secrets
import string

DEFAULT_ALPHABET = string.ascii_letters

_URLSAFE_ALPHABET = string.ascii_letters + string.digits + "-_"

__all__ = ["DEFAULT_ALPHABET", "get_random_string", "get_random_token"]

def get_random_string(length: int, *, alphabet: str = DEFAULT_ALPHABET) -> str:
    """Generate a cryptographically secure random string of a given length.

    Parameters
    ----------
    length:
        Desired output length.
    alphabet:
        Characters to sample from. Defaults to ASCII letters.
    """
    if length < 0:
        raise ValueError("length must be >= 0")
    if not alphabet:
        raise ValueError("alphabet must not be empty")
    return "".join(secrets.choice(alphabet) for _ in range(length))

def get_random_token(length: int = 32) -> str:
    """Generate a URL-safe random token of a given length.

    Parameters
    ----------
    length:
        Desired token length. Defaults to 32.
    """
    return get_random_string(length, alphabet=_URLSAFE_ALPHABET)
