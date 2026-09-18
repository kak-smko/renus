# Random & Secrets

Use cryptographically secure randomness for passwords, reset links, session identifiers, one-time codes, and other values an attacker might guess. Renus exposes secure random helpers through `renus.util`.

## Random strings and tokens

```python
from renus.util import get_random_string, get_random_token

letters_only = get_random_string(24)
custom = get_random_string(8, alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
url_token = get_random_token(32)
```

`get_random_string(length, alphabet=...)` samples each character with Python's `secrets.choice`:

- the default alphabet is ASCII letters (`a-zA-Z`);
- `length` may be zero but not negative;
- an empty alphabet raises `ValueError`.

`get_random_token(length=32)` uses letters, digits, `-`, and `_`, making its output URL-safe without additional escaping. The requested length is the number of output characters, not a promise of a particular byte entropy after every possible alphabet choice. Use a sufficiently long token for the value's risk and lifetime.

Do not use these values as passwords or as encryption keys without applying the key-derivation or key-generation requirements of the cryptographic system you use.

`PrivateResponse` uses `get_random_string(50)` to create a tokenized private-storage path and places the token in the cache. It is not a substitute for an authorization check or an expiry policy; protect the endpoint and configure cache behavior for your application.

## Password hashing

Renus exports `hash_new_password` and `is_correct_password`:

```python
from renus.util import hash_new_password, is_correct_password

stored_hash = hash_new_password("correct horse battery staple")

if is_correct_password(stored_hash, "correct horse battery staple"):
    print("password accepted")
```

`hash_new_password(password)` uses the Python standard library's PBKDF2-HMAC-SHA256 implementation with 600,000 iterations. It generates a fresh 16-byte cryptographically random salt for every password and returns a self-contained value in this format:

```text
<urlsafe-salt>$<urlsafe-digest>
```

The algorithm and iteration prefix are intentionally not included in the returned value. The salt is an implementation detail: do not supply, reuse, or separately store one. Store the complete returned string as the password hash. Hashing the same password twice produces different values, and the salt does not need to be secret.

`is_correct_password(stored_hash, password)` extracts the salt from the stored value, derives a candidate digest, and compares it with a constant-time comparison. Invalid, malformed, or tampered hashes return `False`. Do not log or expose password hashes.

The helper uses no external cryptography dependency. If an application needs to change the KDF or iteration count, it must introduce a versioned storage format and migration strategy rather than changing verification for existing records in place.

## Protecting secrets in models and output

A random token or password hash can still leak through serialization or logging. Mark model fields as sensitive:

```python
from renus.db import Field, Model


class Credential(Model):
    username: str
    password_hash: str = Field(sensitive=True)
    reset_token: str | None = Field(default=None, sensitive=True)
```

Sensitive fields are masked when read as normal model attributes and omitted by default from model serialization. Access a raw value only deliberately with `get_sensitive(name)`. `to_dict(..., include_sensitive=True)` explicitly includes sensitive values and should be used only at a trusted boundary.

For the complete sensitive-field and serialization behavior, see [`/docs/database/fields.md`](/docs/database/fields.md). For recursive masking of parameters, see the serialization API in that same database documentation.

## Secret-handling checklist

- Generate reset, session, and API tokens with `get_random_token()` or another CSPRNG.
- Make tokens single-purpose, scoped, and expiring; store a hash when the token must be recoverable only for comparison.
- Never log passwords, password hashes, session tokens, reset tokens, encryption keys, or decrypted request bodies.
- Use `sensitive=True` for model fields that contain secret material.
- Let `hash_new_password()` generate the per-password salt; salts need not be secret, but peppers and encryption keys do.
- Compare bearer tokens and other secret values without avoidable timing leaks.
- Rotate and revoke credentials through application logic; Renus does not manage their lifecycle.
