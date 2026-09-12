from hashlib import sha3_256

def hash_key(key):
    """Return a stable SHA-3 hex digest for a cache key."""
    return sha3_256(str(key).encode("utf-8")).hexdigest()
