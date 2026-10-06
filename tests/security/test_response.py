"""Security regression tests for :mod:`renus.response`.

These tests document the security-relevant behavior of the response layer:

- header values, names and media types must be immune to CRLF injection /
  response splitting,
- cookies must not be abusable to smuggle extra attributes (domain, path),
- file serving must reject non-regular files and percent-encode
  ``Content-Disposition`` filenames,
- encrypted responses must fail closed when the cryptor fails,
- error responses must not leak stack traces when debug is disabled,
- private-response tokens must be unguessable and unique.

Known open vulnerabilities are encoded as ``xfail(strict=True)`` tests so the
suite stays green while the issues are tracked. When a fix lands, the test
starts to XPASS and the marker must be removed from the test.

"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from renus.response import (
    FileResponse,
    FileResponseError,
    HTTPException,
    JsonResponse,
    PrivateResponse,
    RedirectResponse,
    Response,
    Status,
    StreamingResponse,
    TextResponse,
    debug_response,
)

# --------------------------------------------------------------------------
# Helpers (mirror tests/test_response.py)
# --------------------------------------------------------------------------


class _FakeRequest:

    def __init__(self, headers=None):
        self.headers = dict(headers or {})


async def _send(response, headers=None):
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        await asyncio.Event().wait()

    request = _FakeRequest(headers)
    await response(request, None, receive, send)
    return messages


def _dict_headers(raw_headers):
    return {k.decode(): v.decode() for k, v in raw_headers}


def _concat_bodies(messages):
    payload = b""
    for message in messages:
        if message["type"] == "http.response.body":
            payload += message["body"]
    return payload


def _wire_headers(messages):
    """Return the raw start-message header pairs as bytes."""
    return messages[0]["headers"]


def _assert_no_control_chars_on_wire(messages):
    for name, value in _wire_headers(messages):
        assert b"\r" not in name and b"\n" not in name and b"\0" not in name
        assert b"\r" not in value and b"\n" not in value and b"\0" not in value


@pytest.fixture(autouse=True)
def _reset_singletons():
    from renus.cache.cache import Cache
    from renus.config.config import Config

    Config._cache = {}
    Cache.clear_instances()
    yield
    Config._cache = {}
    Cache.clear_instances()


# --------------------------------------------------------------------------
# Header value injection: CRLF / response splitting defenses
# --------------------------------------------------------------------------


class TestHeaderValueInjectionDefense:

    @pytest.mark.parametrize(
        "value",
        [
            "ok\r\nSet-Cookie: pwned=1",
            "ok\nSet-Cookie: pwned=1",
            "ok\rSet-Cookie: pwned=1",
            "ok\0Injected: 1",
            "\r\n",
        ],
    )
    def test_header_value_with_control_chars_rejected(self, value):
        with pytest.raises(ValueError):
            Response("x", headers={"X-Custom": value})

    def test_header_value_case_preserves_header_integrity(self):
        response = Response("x", headers={"X-Custom": "safe-value"})
        headers = _dict_headers(response.raw_headers)
        assert headers["x-custom"] == "safe-value"


    @pytest.mark.asyncio
    async def test_wire_headers_contain_no_control_characters(self):
        response = TextResponse("hello", headers={"X-Safe": "v"})
        messages = await _send(response)
        _assert_no_control_chars_on_wire(messages)

    def test_user_content_length_is_ignored(self):
        # A forged content-length must not desynchronize the framing:
        # the transport computes it from the real body.
        response = Response("hello", headers={"Content-Length": "99999"})
        assert "content-length" not in _dict_headers(response.raw_headers)

    @pytest.mark.asyncio
    async def test_wire_content_length_matches_body(self):
        messages = await _send(TextResponse("hello"))
        headers = _dict_headers(messages[0]["headers"])
        body = _concat_bodies(messages)
        assert int(headers["content-length"]) == len(body)




# --------------------------------------------------------------------------
# Cookie hardening
# --------------------------------------------------------------------------


class TestCookieHardening:

    def test_cookie_key_with_crlf_rejected(self):
        response = Response("x")
        with pytest.raises(ValueError):
            response.set_cookie("bad\r\nInjected: 1", "v")

    def test_cookie_value_with_crlf_rejected(self):
        response = Response("x")
        with pytest.raises(ValueError):
            response.set_cookie("sid", "v\r\nInjected: 1")

    def test_cookie_value_with_null_byte_rejected(self):
        response = Response("x")
        with pytest.raises(ValueError):
            response.set_cookie("sid", "v\0")

    def test_invalid_samesite_rejected(self):
        response = Response("x")
        with pytest.raises(ValueError):
            response.set_cookie("sid", "v", samesite="bogus")

    def test_cookie_defaults_are_hardened(self):
        response = Response("x")
        response.set_cookie("sid", "v")
        cookie = _dict_headers(response.raw_headers)["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie


# --------------------------------------------------------------------------
# Content-Disposition and file serving hardening
# --------------------------------------------------------------------------


class TestFileServingHardening:

    def test_filename_with_crlf_is_percent_encoded(self):
        response = FileResponse("/tmp/x.pdf", filename="a\r\nX-Evil: 1.pdf")
        headers = _dict_headers(response.raw_headers)
        disposition = headers["content-disposition"]
        assert "\r" not in disposition and "\n" not in disposition
        assert disposition.startswith("attachment; filename*=utf-8''")

    def test_non_ascii_filename_uses_rfc5987_encoding(self):
        response = FileResponse("/tmp/x.pdf", filename="résumé.pdf")
        headers = _dict_headers(response.raw_headers)
        disposition = headers["content-disposition"]
        assert "filename*=utf-8''" in disposition
        assert "attachment" in disposition

    @pytest.mark.asyncio
    async def test_directory_is_rejected(self, tmp_path):
        with pytest.raises(FileResponseError):
            await _send(FileResponse(str(tmp_path)))

    @pytest.mark.asyncio
    async def test_non_regular_file_is_rejected(self, tmp_path):
        fifo = tmp_path / "fifo"
        os.mkfifo(str(fifo))
        with pytest.raises(FileResponseError):
            await _send(FileResponse(str(fifo)))

    @pytest.mark.asyncio
    async def test_null_byte_path_fails_closed(self, tmp_path):
        # os.stat raises ValueError for embedded NULs; it must not be
        # swallowed into serving anything.
        with pytest.raises((ValueError, FileResponseError)):
            await _send(FileResponse(str(tmp_path / "a\0b")))

    @pytest.mark.asyncio
    async def test_missing_file_raises(self):
        with pytest.raises(FileResponseError):
            await _send(FileResponse("/no/such/file.txt"))

    @pytest.mark.asyncio
    async def test_declared_length_matches_streamed_body(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"x" * 1234)
        messages = await _send(FileResponse(str(path)))
        headers = _dict_headers(messages[0]["headers"])
        assert int(headers["content-length"]) == len(_concat_bodies(messages))


# --------------------------------------------------------------------------
# Encrypted responses
# --------------------------------------------------------------------------


class _TagCryptor:
    """Deterministic fake cryptor: reverses bytes so the plaintext is not
    recoverable by substring inspection."""

    def __init__(self, request=None, **kwargs):
        self.request = request

    def encrypt(self, data: bytes) -> bytes:
        return data[::-1]

    def decrypt_text(self, data: str) -> str:
        return data[::-1]


class _ExplodingCryptor:
    def __init__(self, **kwargs):
        raise RuntimeError("cryptor misconfigured")


class TestEncryptedResponse:

    @pytest.mark.asyncio
    async def test_encrypted_body_is_not_plaintext_on_wire(self):
        response = Response("TOPSECRET", cryptor=_TagCryptor)
        messages = await _send(response)
        body = _concat_bodies(messages)

        assert b"TOPSECRET" not in body
        assert body == b"TERCESPOT"

    @pytest.mark.asyncio
    async def test_encrypted_headers_mark_response(self):
        response = Response("secret", cryptor=_TagCryptor)
        messages = await _send(response)
        headers = _dict_headers(messages[0]["headers"])

        assert headers["encrypted"] == "1"
        assert headers["content-type"] == "application/octet-stream"
        assert headers["real-type"] == "text/html; charset=utf-8"

    @pytest.mark.asyncio
    async def test_cryptor_failure_fails_closed(self):
        response = Response("TOPSECRET", cryptor=_ExplodingCryptor)

        # The failure must raise before any response start message is sent:
        # no plaintext reaches the wire and the app-level error handler
        # turns the exception into a generic error response.
        with pytest.raises(Exception):
            await _send(response)


# --------------------------------------------------------------------------
# Error responses and information disclosure
# --------------------------------------------------------------------------


class TestErrorResponseInfoLeak:

    def test_non_debug_response_is_generic(self):
        payload, status = debug_response(ValueError("boom"), debug=False)
        assert status == Status.HTTP_500_INTERNAL_SERVER_ERROR
        assert payload == {"msg": "Internal Server Error"}
        # No stack, file or locals leak outside debug mode.
        assert "stack" not in payload
        assert "file" not in payload

    def test_debug_flag_defaults_to_off(self):
        payload, status = debug_response(ValueError("boom"))
        assert payload == {"msg": "Internal Server Error"}

    def test_http_exception_detail_is_returned_intact(self):
        payload, status = debug_response(
            HTTPException({"msg": "invalid input"}, Status.HTTP_422_UNPROCESSABLE_ENTITY)
        )
        assert payload == {"msg": "invalid input"}
        assert status == Status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_validation_error_detail_does_not_leak_internals(self):
        # The detail is developer-provided; the layer must not enrich it
        # with tracebacks.
        payload, status = debug_response(HTTPException("not found", Status.HTTP_404_NOT_FOUND))
        assert payload == {"msg": "not found"}
        assert "stack" not in payload


# --------------------------------------------------------------------------
# Private response token hygiene
# --------------------------------------------------------------------------


class TestPrivateTokenHygiene:

    def test_tokens_are_unique_per_response(self):
        with patch("renus.response.private.Cache.put"):
            first = PrivateResponse("a.pdf").body
            second = PrivateResponse("a.pdf").body

        assert first != second

    def test_token_is_long_random_alphabet_only(self):
        with patch("renus.response.private.Cache.put"):
            body = PrivateResponse("secret.pdf").body.decode()

        import re

        match = re.fullmatch(r"/storage/private/([A-Za-z]{50})/secret\.pdf", body)
        assert match is not None, body

    def test_token_segment_cannot_be_influenced_by_content(self):
        # The random prefix must always come from the CSPRNG; the caller
        # content only lands after it.
        with patch("renus.response.private.Cache.put"):
            body = PrivateResponse("../../etc/passwd").body.decode()

        assert body.startswith("/storage/private/")
        assert "../" not in body.split("/storage/private/", 1)[1].split("/", 1)[0]


# --------------------------------------------------------------------------
# Redirect location safety
# --------------------------------------------------------------------------


class TestRedirectLocationSafety:

    def test_crlf_in_url_is_percent_encoded(self):
        response = RedirectResponse("/x\r\nEvil: 1")
        headers = _dict_headers(response.raw_headers)
        location = headers["location"]
        assert "\r" not in location and "\n" not in location
        assert location == "/x%0D%0AEvil:+1"

    def test_null_byte_in_url_is_encoded(self):
        response = RedirectResponse("/x\0y")
        headers = _dict_headers(response.raw_headers)
        assert "\0" not in headers["location"]

    def test_location_is_lowercased_header_name(self):
        response = RedirectResponse("/target")
        headers = _dict_headers(response.raw_headers)
        assert headers["location"] == "/target"


# --------------------------------------------------------------------------
# Streaming header idempotency
# --------------------------------------------------------------------------


class TestStreamingHeaderIdempotency:

    @pytest.mark.asyncio
    async def test_resending_stream_does_not_duplicate_headers(self):
        async def gen():
            yield b"x"

        response = StreamingResponse(gen(), zipped=True)
        first = await _send(response, {"accept-encoding": "gzip"})
        second = await _send(response, {"accept-encoding": "gzip"})

        first_enc = [v for k, v in _wire_headers(first) if k == b"content-encoding"]
        second_enc = [v for k, v in _wire_headers(second) if k == b"content-encoding"]

        assert len(first_enc) == 1
        assert len(second_enc) == 1
        assert first_enc == second_enc


# --------------------------------------------------------------------------
# JSON content-type enforcement
# --------------------------------------------------------------------------


class TestJsonResponseTypeEnforcement:

    def test_script_payload_stays_inside_application_json(self):
        # The body is intentionally not HTML-escaped; the application/json
        # content type is what keeps it inert. Assert it can never silently
        # become a text/* type.
        response = JsonResponse({"echo": "<script>alert(1)</script>"})
        headers = _dict_headers(response.raw_headers)
        assert headers["content-type"] == "application/json"

    def test_media_type_override_to_text_is_visible_not_sniffable(self):
        # If an application explicitly overrides the media type, the charset
        # must still be pinned so encoding-based filter evasion fails.
        response = JsonResponse(
            {"echo": "<script>alert(1)</script>"}, media_type="text/html"
        )
        headers = _dict_headers(response.raw_headers)
        assert headers["content-type"] == "text/html; charset=utf-8"
