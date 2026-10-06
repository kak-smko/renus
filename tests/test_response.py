import asyncio
import gzip
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from renus.response import (
    FileResponse,
    FileResponseError,
    GzipStreamer,
    HtmlResponse,
    HTTPException,
    JsonResponse,
    PrivateResponse,
    RedirectResponse,
    Response,
    Status,
    StreamingResponse,
    TextResponse,
    abort,
    abort_if,
    abort_unless,
    debug_response,
)

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

@pytest.fixture(autouse=True)
def _reset_singletons():
    from renus.cache.cache import Cache
    from renus.config.config import Config

    Config._cache = {}
    Cache.clear_instances()
    yield
    Config._cache = {}
    Cache.clear_instances()

class TestGzipStreamer:

    def test_concatenated_deltas_decompress_to_original(self):
        payload = [b"alpha ", b"beta " * 100, b"gamma " * 150, b"delta"]
        gz = GzipStreamer()
        compressed = b"".join(
            piece for piece in (gz.write(chunk) for chunk in payload)
        ) + gz.finish()

        assert compressed.startswith(b"\x1f\x8b")
        assert gzip.decompress(compressed) == b"".join(payload)

    def test_empty_input(self):
        gz = GzipStreamer()
        gz.write(b"")
        gz.finish()

        assert gzip.decompress(gz.compressed()) == b""

    def test_compressed_reports_entire_output(self):
        gz = GzipStreamer()
        gz.write(b"hello world")
        gz.finish()
        assert len(gz.compressed()) > 0

class TestResponse:

    @pytest.mark.parametrize(
        "content,expected",
        [(None, b""), (b"raw", b"raw"), ("text", b"text")],
    )
    def test_render_content(self, content, expected):
        assert Response(content).body == expected

    def test_content_type_gets_charset_for_text(self):
        response = Response("hello")
        headers = _dict_headers(response.raw_headers)
        assert headers["content-type"] == "text/html; charset=utf-8"

    def test_explicit_content_type_kept(self):
        response = Response("x", headers={"Content-Type": "application/json"})
        headers = _dict_headers(response.raw_headers)
        assert headers["content-type"] == "application/json"

    def test_user_headers_are_lowercased(self):
        response = Response("x", headers={"X-Custom-Header": "v"})
        headers = _dict_headers(response.raw_headers)
        assert headers["x-custom-header"] == "v"

    def test_set_cookie_and_delete_cookie(self):
        response = Response("x")
        response.set_cookie("sid", "abc", httponly=True, samesite="strict")
        response.delete_cookie("sid")
        headers = _dict_headers(response.raw_headers)
        assert "set-cookie" in headers

        response.raw_headers = [
            pair for pair in response.raw_headers
            if not pair[0].startswith(b"set-cookie")
        ]
        response.set_cookie("sid", "abc")
        response.delete_cookie("sid")
        cookie = response.raw_headers[-1][1].decode()
        assert "max-age=0" in cookie or "expires" in cookie

    def test_invalid_samesite_raises(self):
        response = Response("x")
        with pytest.raises(ValueError):
            response.set_cookie("k", "v", samesite="bogus")

    def test_repr(self):
        assert "Response" in repr(Response("x"))
        assert "200" in repr(Response("x"))

    @pytest.mark.asyncio
    async def test_send_does_not_mutate_transport_headers_or_body(self):
        response = TextResponse("a" * 1000)
        original_body = response.body
        original_headers = list(response.raw_headers)
        first = await _send(response, {"accept-encoding": "gzip"})
        second = await _send(response, {"accept-encoding": "gzip"})

        assert response.body == original_body
        assert response.raw_headers == original_headers
        assert first[0]["headers"] == second[0]["headers"]
        assert _concat_bodies(first) == _concat_bodies(second)

class TestGzipOnWire:

    @pytest.mark.asyncio
    async def test_large_body_is_gzipped(self):
        body = "a" * 1000
        messages = await _send(TextResponse(body), {"accept-encoding": "gzip"})
        headers = _dict_headers(messages[0]["headers"])
        assert headers["content-encoding"] == "gzip"
        compressed = _concat_bodies(messages)
        assert gzip.decompress(compressed) == body.encode()

    @pytest.mark.asyncio
    async def test_small_body_is_not_gzipped(self):
        messages = await _send(TextResponse("hi"), {"accept-encoding": "gzip"})
        headers = _dict_headers(messages[0]["headers"])
        assert headers["content-encoding"] == "none"

class TestTextResponses:
    def test_html_media_type(self):
        assert HtmlResponse("<p>hi</p>").media_type == "text/html"

    def test_text_media_type_and_rendering(self):
        response = TextResponse(42)
        assert response.media_type == "text/plain"
        assert response.body == b"42"

    def test_text_none_is_empty(self):
        assert TextResponse(None).body == b""

class TestJsonResponses:
    def test_json_renders_dict(self):
        response = JsonResponse({"a": 1})
        assert json.loads(response.body) == {"a": 1}
        assert response.media_type == "application/json"

    def test_json_renders_datetime_via_encoder(self):
        response = JsonResponse({"when": datetime(2024, 1, 2, 3, 4, 5)})
        assert json.loads(response.body) == {"when": "2024-01-02T03:04:05Z"}

class TestRedirectResponse:
    def test_sets_location_header(self):
        response = RedirectResponse("/target")
        headers = _dict_headers(response.raw_headers)
        assert headers["location"] == "/target"
        assert response.status_code == Status.HTTP_307_TEMPORARY_REDIRECT

    def test_encodes_special_characters(self):
        response = RedirectResponse("https://x.test/a b?c=d&e=f")
        headers = _dict_headers(response.raw_headers)

        assert headers["location"] == "https://x.test/a+b?c=d&e=f"

    def test_custom_status_code(self):
        response = RedirectResponse("/x", status_code=Status.HTTP_301_MOVED_PERMANENTLY)
        assert response.status_code == 301

class TestStreamingResponse:
    @pytest.mark.asyncio
    async def test_streams_chunks(self):
        async def gen():
            for part in [b"one", b"two", b"three"]:
                yield part

        messages = await _send(StreamingResponse(gen()))
        assert _concat_bodies(messages) == b"onetwothree"
        bodies = [m for m in messages if m["type"] == "http.response.body"]

        assert all(m["more_body"] is True for m in bodies[:-1])
        assert bodies[-1]["more_body"] is False

    @pytest.mark.asyncio
    async def test_streams_strings(self):
        async def gen():
            for part in ["a", "b"]:
                yield part

        assert _concat_bodies(await _send(StreamingResponse(gen()))) == b"ab"

    @pytest.mark.asyncio
    async def test_stream_gzip_roundtrip(self):
        async def gen():
            for part in [b"x" * 300, b"y" * 300, b"z" * 300]:
                yield part

        messages = await _send(StreamingResponse(gen(), zipped=True),
                               {"accept-encoding": "gzip"})
        headers = _dict_headers(messages[0]["headers"])
        assert headers["content-encoding"] == "gzip"
        assert gzip.decompress(_concat_bodies(messages)) == b"x" * 300 + b"y" * 300 + b"z" * 300

class TestFileResponse:
    @pytest.mark.asyncio
    async def test_serves_file_contents(self, tmp_path):
        path = tmp_path / "hello.txt"
        path.write_bytes(b"hello file")
        messages = await _send(FileResponse(str(path)))
        assert _concat_bodies(messages) == b"hello file"

    @pytest.mark.asyncio
    async def test_headers_and_etag(self, tmp_path):
        path = tmp_path / "a.txt"
        path.write_bytes(b"data")
        messages = await _send(FileResponse(str(path)))
        headers = _dict_headers(messages[0]["headers"])
        assert headers["content-type"].startswith("text/plain")
        assert "etag" in headers
        assert "last-modified" in headers
        assert "content-length" in headers

    @pytest.mark.asyncio
    async def test_head_sends_no_body(self, tmp_path):
        path = tmp_path / "a.txt"
        path.write_bytes(b"data")
        messages = await _send(FileResponse(str(path), method="HEAD"))
        bodies = [m for m in messages if m["type"] == "http.response.body"]
        assert bodies == [{"type": "http.response.body", "body": b"",
                           "more_body": False}]

    @pytest.mark.asyncio
    async def test_missing_file_raises_file_response_error(self):
        with pytest.raises(FileResponseError):
            await _send(FileResponse("/no/such/file.txt"))

    @pytest.mark.asyncio
    async def test_file_response_error_is_runtime_error(self):
        assert issubclass(FileResponseError, RuntimeError)

    @pytest.mark.asyncio
    async def test_gzip_file_roundtrip(self, tmp_path):
        path = tmp_path / "big.txt"
        data = b"p" * 5000
        path.write_bytes(data)
        messages = await _send(FileResponse(str(path)), {"accept-encoding": "gzip"})
        headers = _dict_headers(messages[0]["headers"])
        assert headers["content-encoding"] == "gzip"
        assert gzip.decompress(_concat_bodies(messages)) == data

class TestPrivateResponse:
    def test_renders_tokenised_path_and_puts_cache(self):
        with patch("renus.response.private.Cache.put") as put_mock, \
                patch("renus.response.private.get_random_string") as rnd:
            rnd.return_value = "tok" * 16 + "a" * 2
            response = PrivateResponse("secret.pdf")

        assert response.media_type == "text/plain"
        assert response.body.decode() == f"/storage/private/{'tok'*16 + 'a'*2}/secret.pdf"
        put_mock.assert_called_once()

class TestStatus:
    def test_constants(self):
        assert Status.HTTP_200_OK == 200
        assert Status.HTTP_404_NOT_FOUND == 404
        assert Status.HTTP_500_INTERNAL_SERVER_ERROR == 500

    def test_websocket_codes(self):
        assert Status.WS_1000_NORMAL_CLOSURE == 1000
        assert Status.WS_1003_UNSUPPORTED_DATA == 1003

class TestHTTPExceptions:
    def test_string_detail_wrapped_in_msg(self):
        exc = HTTPException("boom")
        assert exc.detail == {"msg": "boom"}
        assert exc.status_code == Status.HTTP_400_BAD_REQUEST

    def test_default_status_is_400(self):
        assert HTTPException("x").status_code == 400

    def test_abort_raises(self):
        with pytest.raises(HTTPException) as info:
            abort("nope")
        assert info.value.status_code == 400

    def test_abort_if(self):
        with pytest.raises(HTTPException):
            abort_if(1 == 1, "yes")

        abort_if(1 == 2, "no")

    def test_abort_unless(self):
        with pytest.raises(HTTPException):
            abort_unless(1 == 2, "not ok")
        abort_unless(1 == 1, "ok")

class TestDebugResponse:
    def test_http_exception_returned_as_pair(self):
        payload, status = debug_response(HTTPException({"msg": "x"}, 403))
        assert payload == {"msg": "x"}
        assert status == 403

    def test_legacy_runtime_error_pair(self):
        result = debug_response(RuntimeError({"msg": "legacy"}, 418))
        assert result == ({"msg": "legacy"}, 418)

    def test_unknown_error_is_500_without_debug(self):
        payload, status = debug_response(ValueError("boom"), debug=False)
        assert status == 500
        assert payload == {"msg": "Internal Server Error"}
