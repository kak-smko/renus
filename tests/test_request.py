from unittest.mock import patch

import pytest

from renus.request import (
    ClientDisconnect,
    Injection,
    Request,
    Xss,
    cookie_parser,
    headers_parser,
    parse_options_header,
    query_parser,
)

def _scope(**overrides):
    base = {
        "type": "http",
        "scheme": "http",
        "server": ("example.com", 80),
        "path": "/hello",
        "query_string": b"",
        "headers": [
            (b"host", b"example.com"),
            (b"user-agent", b"test-agent"),
            (b"cookie", b'sid="abc"; theme=dark'),
        ],
    }
    base.update(overrides)
    return base

def _make_request(body_messages=None, **scope_overrides):
    messages = body_messages if body_messages is not None else [{"type": "http.request", "body": b""}]
    queue = list(messages)

    async def receive():
        return queue.pop(0)

    return Request(_scope(**scope_overrides), receive)

@pytest.fixture(autouse=True)
def _reset_singletons():
    from renus.config.config import Config

    Config._cache = {}
    yield
    Config._cache = {}

class TestConnectionMetadata:

    def test_headers_are_lowercased(self):
        req = _make_request(headers=[(b"X-Custom", b"1"), (b"Host", b"example.com")])
        assert req.headers["x-custom"] == "1"
        assert "Host" not in req.headers

    def test_cookies_parsed(self):
        req = _make_request()
        assert req.cookies == {"sid": "abc", "theme": "dark"}

    def test_cookies_empty_without_header(self):
        req = _make_request(headers=[(b"host", b"example.com")])
        assert req.cookies == {}

    def test_client_pair(self):
        req = _make_request(client=("1.2.3.4", 5678))
        assert req.client == ("1.2.3.4", 5678)

    def test_ip_from_client(self):
        req = _make_request(client=("1.2.3.4", 5678))
        assert req.ip == "1.2.3.4"

    def test_ip_from_configured_header(self):
        req = _make_request(headers=[(b"host", b"example.com"), (b"x-real-ip", b"9.9.9.9")])
        with patch("renus.config.Config.get", return_value="x-real-ip"):
            assert req.ip == "9.9.9.9"

    def test_subdomain_plain_host(self):
        req = _make_request()
        assert req.subdomain == "example"

    def test_subdomain_none_for_localhost(self):
        req = _make_request(headers=[(b"host", b"localhost")])
        assert req.subdomain is None

    def test_subdomain_none_for_ip(self):
        req = _make_request(headers=[(b"host", b"192.168.0.1")])
        assert req.subdomain is None

    def test_user_agent(self):
        assert _make_request().user_agent == "test-agent"

    def test_method_normalized_uppercase(self):
        req = _make_request(method="post")
        assert req.method == "POST"

    def test_url_alias_equals_full_path(self):
        req = _make_request(query_string=b"a=1")
        assert req.url == req.full_path == "http://example.com/hello?a=1"

class TestURLBuilding:

    def test_base_path_uses_host_header(self):
        assert _make_request().base_path == "http://example.com"

    def test_base_path_from_server_on_non_default_port(self):
        req = _make_request(server=("example.com", 8080), headers=[])
        assert req.base_path == "http://example.com:8080"

    def test_base_path_omits_default_port(self):
        assert _make_request(headers=[]).base_path == "http://example.com"

    def test_full_path_includes_query(self):
        req = _make_request(query_string=b"q=hi&n=2")
        assert req.full_path == "http://example.com/hello?q=hi&n=2"

    def test_full_path_with_root_path(self):
        req = _make_request(root_path="/app", path="/hi", query_string=b"")
        assert req.full_path == "http://example.com/app/hi"

    def test_query_params_decoded(self):
        req = _make_request(query_string=b"a=1&b=two")
        assert req.query_params == {"a": "1", "b": "two"}

class TestBodyAndForm:

    @pytest.mark.asyncio
    async def test_body_concatenates_chunks(self):
        req = _make_request(
            [
                {"type": "http.request", "body": b"he", "more_body": True},
                {"type": "http.request", "body": b"llo", "more_body": False},
            ]
        )
        assert await req.body() == b"hello"

    @pytest.mark.asyncio
    async def test_body_is_cached(self):
        req = _make_request([{"type": "http.request", "body": b"x", "more_body": False}])
        assert await req.body() == b"x"
        assert await req.body() == b"x"

    @pytest.mark.asyncio
    async def test_stream_after_consumed_raises(self):
        req = _make_request()
        async for _ in req.stream():
            pass
        with pytest.raises(RuntimeError):
            async for _ in req.stream():
                pass

    @pytest.mark.asyncio
    async def test_form_json(self):
        req = _make_request(
            [{"type": "http.request", "body": b'{"a": 1}', "more_body": False}],
            headers=[(b"host", b"example.com"), (b"content-type", b"application/json")],
        )
        assert await req.form() == {"a": 1}

    @pytest.mark.asyncio
    async def test_form_empty_body_is_empty_dict(self):
        req = _make_request()
        assert await req.form() == {}

    @pytest.mark.asyncio
    async def test_form_bad_json_falls_back_empty(self):
        req = _make_request(
            [{"type": "http.request", "body": b"not json", "more_body": False}],
            headers=[(b"host", b"example.com"), (b"content-type", b"application/json")],
        )
        assert await req.form() == {}

    @pytest.mark.asyncio
    async def test_form_urlencoded(self):
        body = b"name=Renus&age=10"
        req = _make_request(
            [{"type": "http.request", "body": body, "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
        )
        assert await req.form() == {"name": "Renus", "age": "10"}

    @pytest.mark.asyncio
    async def test_form_urlencoded_legacy_content_type(self):
        body = b"a=1"
        req = _make_request(
            [{"type": "http.request", "body": body, "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"app/x-www-form-urlencoded"),
            ],
        )
        assert await req.form() == {"a": "1"}

    @pytest.mark.asyncio
    async def test_form_multipart_fields_and_file(self):
        boundary = "bndry"
        part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="title"\r\n\r\n'
            f"Hello\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="f"; filename="a.txt"\r\n'
            f'Content-Type: text/plain\r\n\r\n'
            f"filebody\r\n"
            f"--{boundary}--\r\n"
        )
        req = _make_request(
            [{"type": "http.request", "body": part.encode(), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", f'multipart/form-data; boundary="{boundary}"'.encode()),
            ],
        )
        form = await req.form()
        assert form["title"] == "Hello"
        upload = form["f"]
        assert upload.filename == "a.txt"
        assert upload.content_type == "text/plain"
        await upload.seek(0)
        assert await upload.read() == b"filebody"

    @pytest.mark.asyncio
    async def test_form_protects_inputs_from_injection(self):
        req = _make_request(
            [{"type": "http.request", "body": b'{"x": "<script>alert(1)</script>"}', "more_body": False}],
            headers=[(b"host", b"example.com"), (b"content-type", b"application/json")],
        )
        safe = await req.form()
        assert "<script" not in safe["x"]

    @pytest.mark.asyncio
    async def test_form_unsafe_returns_raw_data(self):
        req = _make_request(
            [{"type": "http.request", "body": b'{"x": "<script>alert(1)</script>"}', "more_body": False}],
            headers=[(b"host", b"example.com"), (b"content-type", b"application/json")],
        )
        raw = await req.form_unsafe()
        assert raw["x"] == "<script>alert(1)</script>"

    @pytest.mark.asyncio
    async def test_form_non_dict_returns_empty(self):
        req = _make_request(
            [{"type": "http.request", "body": b"plain", "more_body": False}],
            headers=[(b"host", b"example.com"), (b"content-type", b"application/json")],
        )
        assert await req.form() == {}

class TestEncryptedBody:

    @pytest.mark.asyncio
    async def test_decrypt_json_real_type(self):
        class Dummy:
            def __init__(self, request):
                self.request = request

            def decrypt_text(self, text):
                return text[::-1]

        setattr(Request, "cryptor", Dummy)

        body = '{"a": 1}'[::-1]
        req = _make_request(
            [{"type": "http.request", "body": body.encode(), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"encrypted", b"1"),
                (b"real-type", b"application/json"),
            ],
        )
        assert await req.form() == {"a": 1}
        setattr(Request, "cryptor", None)

    @pytest.mark.asyncio
    async def test_encrypted_without_cryptor_raises(self):
        Request.cryptor = None
        req = _make_request(
            [{"type": "http.request", "body": b"xyz", "more_body": False}],
            headers=[(b"host", b"example.com"), (b"encrypted", b"1")],
        )
        with pytest.raises(ValueError):
            await req.form()

class TestClientDisconnect:

    @pytest.mark.asyncio
    async def test_stream_raises_on_disconnect(self):
        req = _make_request([{"type": "http.disconnect"}])
        with pytest.raises(ClientDisconnect):
            async for _ in req.stream():
                pass

    @pytest.mark.asyncio
    async def test_body_propagates_disconnect(self):
        req = _make_request([{"type": "http.disconnect"}])
        with pytest.raises(ClientDisconnect):
            await req.body()

class TestParsers:

    def test_headers_skip_invalid_names(self):
        out = headers_parser([(b"bad name", b"x"), (b"ok", b"1")])
        assert out == {"ok": "1"}

    def test_headers_strip_control_chars(self):
        out = headers_parser([(b"x", b"a\x00b\x1fc")])
        assert out == {"x": "abc"}

    def test_cookie_unquotes_and_splits(self):
        assert cookie_parser('a="1"; b=two; c="xy"') == {"a": "1", "b": "two", "c": "xy"}

    def test_cookie_ignores_empty_segments(self):
        assert cookie_parser(";; a=1 ;;") == {"a": "1"}

    def test_query_parser_keeps_blanks(self):
        assert query_parser(b"a=1&b=") == {"a": "1", "b": ""}

    def test_headers_too_many_raises(self):
        from renus.request.limits import MAX_HEADERS

        many = [(b"x", b"1")] * (MAX_HEADERS + 1)
        with pytest.raises(RuntimeError):
            headers_parser(many)

class TestOptions:

    def test_plain_value(self):
        assert parse_options_header("text/plain") == ("text/plain", {})

    def test_with_options(self):
        value, opts = parse_options_header("multipart/form-data; boundary=abc; charset=utf-8")
        assert value == "multipart/form-data"
        assert opts == {"boundary": "abc", "charset": "utf-8"}

    def test_quoted_semicolon_in_filename(self):
        value, opts = parse_options_header('form-data; filename="a;b.txt"')
        assert value == "form-data"
        assert opts == {"filename": "a;b.txt"}

    def test_none_and_empty(self):
        assert parse_options_header(None) == ("", {})
        assert parse_options_header("") == ("", {})

class TestInjectionProtection:

    def test_escape_script_tag(self):
        out = Injection().escape('<script>alert(1)</script>')

        assert "<script" not in out
        assert "scripts" in out

    def test_protect_recursively(self):
        data: dict = {"nested": {"x": "<b>hi</b>"}, "safe": "ok", "n": 2}
        out: dict = Injection().protect(data)
        assert out["safe"] == "ok"
        assert out["n"] == 2
        assert out["nested"]["x"] is not None

    def test_protect_leaves_primitives(self):
        assert Injection().protect(3) == 3
        assert Injection().protect(True) is True
        assert Injection().protect("3") == "3"

    def test_xss_rewrites_javascript_url(self):
        out = Xss()
        out.feed('<a href="javascript:alert(1)">x</a>')
        out.close()

        assert "http://javascript:" in out.getEscaped()

    def test_xss_allowlist_keeps_images(self):
        out = Xss()
        out.feed('<img src="http://ok/x.png">')
        out.close()
        assert "img" in out.getEscaped()
