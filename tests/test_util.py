from __future__ import annotations

import string

import pytest

from renus.util import (
    CodecError,
    add_pad64,
    decode64,
    encode64,
    get_random_string,
    get_random_token,
    hash_new_password,
    is_correct_password,
    remove_pad64,
)

class TestSecurity:
    def test_hash_is_self_contained_and_randomized(self):
        first = hash_new_password("s3cret")
        second = hash_new_password("s3cret")
        assert not first.startswith("pbkdf2_sha256$600000$")
        assert len(first.split("$")) == 2
        assert first != second

    def test_matches_correct_password(self):
        stored = hash_new_password("s3cret")
        assert is_correct_password(stored, "s3cret") is True

    def test_rejects_wrong_password(self):
        stored = hash_new_password("s3cret")
        assert is_correct_password(stored, "wrong") is False


    def test_unrelated_hash_does_not_match(self):
        other = hash_new_password("other-password")
        assert is_correct_password(other, "s3cret") is False

    def test_unicode_password_round_trips(self):
        stored = hash_new_password("s3crét-🙂")
        assert is_correct_password(stored, "s3crét-🙂") is True

class TestRandom:

    def test_random_string_length(self):
        assert len(get_random_string(12)) == 12
        assert len(get_random_string(0)) == 0

    def test_random_string_uses_default_alphabet(self):
        value = get_random_string(256)
        assert all(c in string.ascii_letters for c in value)

    def test_random_string_respects_custom_alphabet(self):
        value = get_random_string(64, alphabet="ab")
        assert all(c in "ab" for c in value)
        assert value

    def test_negative_length_raises(self):
        with pytest.raises(ValueError):
            get_random_string(-1)

    def test_empty_alphabet_raises(self):
        with pytest.raises(ValueError):
            get_random_string(4, alphabet="")

    def test_urlsafe_token(self):
        token = get_random_token(32)
        assert len(token) == 32
        assert all(c in string.ascii_letters + string.digits + "-_" for c in token)

    def test_default_token_length(self):
        assert len(get_random_token()) == 32

    def test_produces_varied_output(self):
        seen = {get_random_string(20) for _ in range(200)}
        assert len(seen) > 1

class TestCodec:
    def test_padding_helpers_are_inverse(self):
        sample = "YWJj"
        assert add_pad64("YWJ") == "YWJ="
        assert add_pad64(sample) == sample
        assert remove_pad64("YWJ=") == "YWJ"
        assert remove_pad64(sample) == sample

    def test_round_trips_strings_and_numbers(self):
        assert decode64(encode64("hello")) == "hello"
        assert decode64(encode64(42)) == 42
        assert decode64(encode64(3.14)) == 3.14

    def test_round_trips_unicode(self):
        assert decode64(encode64("héllo 世界 🙂")) == "héllo 世界 🙂"

    def test_round_trips_nested_structure(self):
        payload = {"user": 7, "roles": ["admin", "editor"], "active": True}
        assert decode64(encode64(payload)) == payload

    def test_encode64_is_urlsafe_and_unpadded(self):
        token = encode64({"k": "v"})
        assert "=" not in token
        assert "/" not in token and "+" not in token

    def test_decode_accepts_padded_variant(self):
        payload = {"user": 7}
        token = encode64(payload)
        padded = add_pad64(token)
        assert decode64(padded) == payload

    def test_decoder_object_hook_is_applied(self):

        import datetime as _dt

        payload = {"data": {"expires": "2026-01-02T03:04:05Z"}}

        def _convert(value):
            if isinstance(value, dict) and "expires" in value:
                return _dt.datetime.fromisoformat(value["expires"])
            return value

        decoded = decode64(encode64(payload), decoder=_convert)
        expected = _dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)
        assert decoded["data"] == expected

    def test_invalid_base64_raises_codec_error(self):
        with pytest.raises(CodecError):
            decode64("!!!not-base64!!!")

    def test_invalid_json_raises_codec_error(self):

        token = "bm90IGpzb24"
        with pytest.raises(CodecError):
            decode64(token)

    def test_invalid_utf8_raises_codec_error(self):

        import base64 as _b64

        token = _b64.urlsafe_b64encode(b"\xb6\xb6").decode("ascii").rstrip("=")
        with pytest.raises(CodecError):
            decode64(token)

    def test_codec_error_is_a_runtime_error(self):

        with pytest.raises(RuntimeError):
            decode64("!!!not-base64!!!")
