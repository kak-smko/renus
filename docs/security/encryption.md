# Encryption

Renus supports optional application-provided encryption for HTTP bodies. The `user/crypt.py` example provides a concrete cryptor named `Crypto`; Renus only supplies the request/response integration.

The integration expects a cryptor class or callable with these methods:

- request decryption: `decrypt_text(text)` on `cryptor(request=request)`;
- response encryption: `encrypt(body)` on `cryptor(request=request)`.

## Configure `Crypto`

Configure the cryptor once during application startup, before the server begins handling requests:

```python
from extension.codenus.user.crypt import Crypto
from renus.request import Request
from renus.response import JsonResponse,TextResponse


JsonResponse.cryptor = Crypto
TextResponse.cryptor = Crypto
Request.cryptor = Crypto
```

These two assignments enable opposite directions of the HTTP exchange:

| Assignment | Used for | What Renus does |
| --- | --- | --- |
| `JsonResponse.cryptor = Crypto` | Server-to-client responses | Creates `Crypto(request=request)` and calls `encrypt(body)`. |
| `Request.cryptor = Crypto` | Client-to-server requests | Creates `Crypto(request=request)` and calls `decrypt_text(text)`. |

Assign the class, not an already-created object:

```python
# Correct: Renus creates a request-bound Crypto instance when needed.
JsonResponse.cryptor = Crypto
Request.cryptor = Crypto

# Incorrect for this integration: this creates one instance without a request.
# JsonResponse.cryptor = Crypto()
```

`JsonResponse.cryptor = Crypto` changes the default for `JsonResponse`. Individual responses can still override it by passing `cryptor=...`. `Request.cryptor = Crypto` changes the default for all incoming `Request` objects.

### Why `request.auth_params` matters

`Crypto` does not use one hard-coded application-wide AES key. Its constructor starts with `secure_key`, then, when the request has `auth_params`, reads the hexadecimal per-session key from `auth_params["shared_key"]`:

```python
from user.crypt import Crypto


crypto = Crypto(request=request)
# Equivalent source of the key inside user/crypt.py:
# crypto.shared_key = bytes.fromhex(
#     request.auth_params.get("shared_key", "")
# )
```

In the `user/*` flow, authentication middleware sets `request.auth_params` after it validates the bearer token. The token was created with a `shared_key` value during the client key-exchange flow. The order is therefore:

1. The client establishes a shared key with the server.
2. The server stores that key in the issued token's parameters.
3. Authentication middleware validates the token and sets `request.auth_params`.
4. `Crypto(request=request)` reads `shared_key` from those parameters.
5. Renus decrypts the request body or encrypts the response body.

A route that runs before authentication has no `request.auth_params["shared_key"]`. In the current `Crypto` implementation, encryption then raises `ValueError("shared_key_not_set")`. Do not expect the login or initial key-exchange response to use this per-session body encryption before the shared key exists.

## How `user.crypt.Crypto` works

The `Crypto` implementation in `user/crypt.py` uses:

- elliptic-curve `SECP256R1` for the key-agreement helper methods;
- AES-GCM for authenticated encryption;
- a random 12-byte IV for each encrypted body;
- a SHA-256 digest of the ECDH shared secret as the AES key.

`Crypto` needs a shared key before it can encrypt or decrypt. It can receive one directly through `secure_key`, or it tries to read a hexadecimal `shared_key` from `request.auth_params`:

```python
class Crypto:
    def __init__(self, secure_key: bytes = None, request=None):
        self.shared_key = secure_key
        if hasattr(request, "auth_params"):
            self.shared_key = bytes.fromhex(
                request.auth_params.get("shared_key", "")
            )
```

In the `user/crypt.py` implementation, `generate_server_keys()` creates a server private/public key pair. `set_client_public_key(...)` loads the server private key from `Config("app").get("private_key")`, performs ECDH with the client's public key, and derives `shared_key`. That key-establishment flow is application code; Renus does not call these methods automatically.

A missing shared key causes `Crypto.encrypt()` and `Crypto.decrypt()` to raise `ValueError("shared_key_not_set")`.

## Encrypting a JSON response

After the class-level configuration, route handlers can return normal JSON responses:

```python
from renus.response import JsonResponse


@app.get("/private-data")
async def private_data():
    return JsonResponse({"value": "private"})
```

When Renus sends this response, it calls the equivalent of:

```python
cryptor = Crypto(request=request)
encrypted_body = cryptor.encrypt(response_body)
```

`Crypto.encrypt()` returns the 12-byte IV followed by the AES-GCM ciphertext and authentication tag. Renus then sends those raw encrypted bytes and adds these headers:

```text
encrypted: 1
real-type: application/json
content-type: application/octet-stream
```

The original media type is in `real-type`; the wire body is binary encrypted data. Renus also exposes `encrypted` and `real-type` through `access-control-expose-headers`.

### Current `Crypto` wire-format caveat

`user/crypt.py` also defines `encrypt_text()`, which base64-encodes the encrypted bytes, and `decrypt_text()`, which base64-decodes before decrypting. However, Renus's response path calls `encrypt(body)`, not `encrypt_text(body)`, while its request path calls `decrypt_text(text)`. Therefore the current `Crypto` class does not provide a direct response-to-request round trip without an adapter or a matching client/server wire-format change:

- response output: raw `IV + ciphertext + tag` bytes;
- request input expected by `decrypt_text()`: base64 text containing `IV + ciphertext + tag`.

If your client sends encrypted request bodies to Renus, send the base64 form expected by `decrypt_text()`. If the client must decrypt Renus responses with `decrypt_text()`-compatible logic, either base64-decode the response body before decryption or change the cryptor integration consistently on both sides. Do not make this change on only one side.

The `cryptor` response argument is available on the base `Response` and response subclasses that pass it through, including `JsonResponse`. See [`/docs/development/response.md`](/docs/development/response.md) for the response API.

The response implementation catches an exception from `encrypt()` and falls back to an unencrypted response. Treat that fallback as a deployment concern: if encryption is mandatory, add an application-level check or middleware so a cryptor failure cannot silently disclose the body.

## Decrypting a request

The `Request.cryptor = Crypto` assignment from the configuration section enables decryption. A client marks an encrypted body with `encrypted: 1`. It may include `real-type` so Renus can parse the decrypted plaintext correctly:

```text
encrypted: 1
real-type: application/json
content-type: application/octet-stream
```

When `await request.form()` or `await request.form_unsafe()` sees `encrypted: 1`, Renus:

1. reads the request body;
2. creates `cryptor(request=request)`;
3. calls `decrypt_text()` with the UTF-8 body text;
4. decodes JSON when `real-type` contains `application/json`;
5. parses URL-encoded data when `real-type` contains `application/x-www-form-urlencoded`;
6. otherwise returns the decrypted text as form data input.

If no request cryptor is configured, Renus raises `ValueError`. A decryption failure is also raised as `ValueError`. Handle these failures at your application boundary rather than treating the payload as valid input.

`request.form()` still applies XSS sanitization after decryption. `request.form_unsafe()` does not; see [`/docs/security/xss.md`](/docs/security/xss.md).

## What this does not provide

Renus's body encryption integration does not provide:

- key generation, storage, rotation, or revocation;
- authentication or authorization;
- replay protection;
- nonce/IV management;
- algorithm negotiation;
- password hashing;
- TLS replacement.

Use HTTPS even when application-level body encryption is enabled. Keep keys in a secret manager or protected deployment configuration, rotate them deliberately, and authenticate ciphertext so tampering is detected. Do not put keys in source code, query strings, cookies, or client-controlled headers.

For password hashing and cryptographically secure tokens, see [`/docs/security/random_secrets.md`](/docs/security/random_secrets.md).
