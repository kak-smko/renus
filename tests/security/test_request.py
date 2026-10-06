"""Security regression tests for :mod:`renus.request`.

These tests document the security-relevant behavior of the request layer:

- header parsing must be immune to CRLF injection / response splitting,
- cookie, query and header limits must fail closed,
- body and multipart limits must hold across chunked streams,
- the multipart parser must survive malformed input without crashing,
- the XSS sanitizer must block tag, attribute and URL-based injection vectors,
- encrypted-body parsing must fail closed when decryption is not possible,
- Host-derived values (subdomain) must not be spoofable into trusted names.
"""

from __future__ import annotations

import pytest

from renus.config.config import Config
from renus.request import (
    Injection,
    Request,
    Xss,
    cookie_parser,
    headers_parser,
    query_parser,
)

# --------------------------------------------------------------------------
# Helpers (mirror tests/test_request.py)
# --------------------------------------------------------------------------


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
        ],
    }
    base.update(overrides)
    return base


def _make_request(body_messages=None, **scope_overrides):
    messages = body_messages if body_messages is not None else [
        {"type": "http.request", "body": b""}
    ]
    queue = list(messages)

    async def receive():
        return queue.pop(0)

    return Request(_scope(**scope_overrides), receive)


def _escape(html: str) -> str:
    sanitizer = Xss()
    sanitizer.feed(html)
    sanitizer.close()
    return sanitizer.getEscaped()


def _multipart_body(fields, boundary="bndry"):
    parts = []
    for name, value in fields:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    parts.append(f"--{boundary}--\r\n")
    return "".join(parts).encode()


@pytest.fixture(autouse=True)
def _reset_singletons():
    Config._cache = {}
    yield
    Config._cache = {}


# --------------------------------------------------------------------------
# Header parsing: CRLF injection / response splitting
# --------------------------------------------------------------------------


class TestHeaderInjectionDefense:

    def test_header_value_strips_crlf(self):
        out = headers_parser([(b"x", b"a\r\nSet-Cookie: injected=1")])
        assert "\r" not in out["x"]
        assert "\n" not in out["x"]

    def test_no_parsed_header_contains_control_characters(self):
        raw = [
            (b"host", b"example.com\r\nEvil: 1"),
            (b"x", b"a\x00b\x0bc\x1fd"),
            (b"y", b"tab\tkept"),
        ]
        parsed = headers_parser(raw)
        for value in parsed.values():
            assert "\r" not in value
            assert "\n" not in value
            assert "\x00" not in value

    def test_header_name_with_invalid_characters_skipped(self):
        # A space or slash in the name is a request-smuggling indicator.
        out = headers_parser([(b"bad name", b"x"), (b"bad/name", b"y"), (b"ok", b"1")])
        assert out == {"ok": "1"}

    def test_oversized_header_value_raises(self):
        with pytest.raises(RuntimeError):
            headers_parser([(b"x", b"y" * 9000)])

    def test_too_many_headers_raises(self):
        from renus.request.limits import MAX_HEADERS

        with pytest.raises(RuntimeError):
            headers_parser([(b"x", b"1")] * (MAX_HEADERS + 1))

    def test_header_count_check_precedes_name_validation(self):
        # Invalid names cannot be used to bypass the header count limit.
        from renus.request.limits import MAX_HEADERS

        many_invalid = [(b"bad name", b"1")] * (MAX_HEADERS + 1)
        with pytest.raises(RuntimeError):
            headers_parser(many_invalid)

    def test_non_utf8_header_value_does_not_crash(self):
        out = headers_parser([(b"x", b"a\xffb")])
        assert isinstance(out["x"], str)


# --------------------------------------------------------------------------
# Cookie parsing hardening
# --------------------------------------------------------------------------


class TestCookieParsingHardening:

    def test_oversized_cookie_header_raises(self):
        with pytest.raises(RuntimeError):
            cookie_parser("a=" + "x" * 5000)

    def test_cookie_count_capped(self):
        from renus.request.limits import MAX_COOKIES

        raw = "; ".join(f"k{i}=v" for i in range(MAX_COOKIES + 10))
        cookies = cookie_parser(raw)
        assert len(cookies) <= MAX_COOKIES

    def test_cookie_value_control_chars_stripped(self):
        cookies = cookie_parser("a=\x01\x02b; c=d")
        assert cookies == {"a": "b", "c": "d"}

    def test_cookie_value_strips_crlf(self):
        cookies = cookie_parser("a=x\r\nSet-Cookie: injected=1")
        assert "\r" not in cookies["a"]
        assert "\n" not in cookies["a"]

    def test_cookie_quoted_value_unescaped(self):
        assert cookie_parser('a="1"') == {"a": "1"}


# --------------------------------------------------------------------------
# Query string hardening
# --------------------------------------------------------------------------


class TestQueryStringHardening:

    def test_oversized_query_raises(self):
        with pytest.raises(RuntimeError):
            query_parser(b"a=" + b"x" * 2000)

    def test_oversized_query_raises_via_request(self):
        req = _make_request(query_string=b"a=" + b"x" * 2000)
        with pytest.raises(RuntimeError):
            req.query_params

    def test_null_byte_stripped_from_values(self):
        assert query_parser(b"a=1\x00&b=2") == {"a": "1", "b": "2"}

    def test_encoded_crlf_stripped_from_values(self):
        parsed = query_parser(b"a=1%0d%0aX-Evil:%201")
        assert "\r" not in parsed["a"]
        assert "\n" not in parsed["a"]


# --------------------------------------------------------------------------
# Body and form size limits (DoS protection)
# --------------------------------------------------------------------------


class TestBodySizeLimits:

    @pytest.mark.asyncio
    async def test_body_over_limit_raises(self, monkeypatch):
        monkeypatch.setattr("renus.request.request.MAX_BODY_SIZE", 10)
        req = _make_request([
            {"type": "http.request", "body": b"x" * 11, "more_body": False},
        ])
        with pytest.raises(RuntimeError, match="too large"):
            await req.body()

    @pytest.mark.asyncio
    async def test_body_limit_counts_across_chunks(self, monkeypatch):
        monkeypatch.setattr("renus.request.request.MAX_BODY_SIZE", 10)
        req = _make_request([
            {"type": "http.request", "body": b"x" * 6, "more_body": True},
            {"type": "http.request", "body": b"x" * 6, "more_body": False},
        ])
        with pytest.raises(RuntimeError, match="too large"):
            await req.body()

    @pytest.mark.asyncio
    async def test_body_under_limit_accepted(self, monkeypatch):
        monkeypatch.setattr("renus.request.request.MAX_BODY_SIZE", 10)
        req = _make_request([
            {"type": "http.request", "body": b"x" * 10, "more_body": False},
        ])
        assert await req.body() == b"x" * 10

    @pytest.mark.asyncio
    async def test_urlencoded_over_limit_raises(self, monkeypatch):
        monkeypatch.setattr("renus.request.formparsers.MAX_BODY_SIZE", 10)
        req = _make_request(
            [{"type": "http.request", "body": b"a=" + b"x" * 20, "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
        )
        with pytest.raises(RuntimeError, match="too large"):
            await req.form_unsafe()

    @pytest.mark.asyncio
    async def test_multipart_over_limit_raises(self, monkeypatch):
        monkeypatch.setattr("renus.request.formparsers.MAX_BODY_SIZE", 10)
        req = _make_request(
            [{"type": "http.request", "body": _multipart_body([("a", "x" * 20)]), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data; boundary=bndry"),
            ],
        )
        with pytest.raises(RuntimeError, match="too large"):
            await req.form_unsafe()


# --------------------------------------------------------------------------
# Multipart parsing hardening
# --------------------------------------------------------------------------


class TestMultipartHardening:

    @pytest.mark.asyncio
    async def test_missing_boundary_rejected(self):
        req = _make_request(
            [{"type": "http.request", "body": _multipart_body([("a", "1")]), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data"),
            ],
        )
        with pytest.raises(ValueError):
            await req.form_unsafe()

    @pytest.mark.asyncio
    async def test_mismatched_boundary_yields_no_parts(self):
        # An attacker-declared boundary that does not match the body must not
        # fall back to parsing the raw body as parts.
        req = _make_request(
            [{"type": "http.request", "body": _multipart_body([("a", "1")], boundary="wrong"), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data; boundary=bndry"),
            ],
        )
        assert await req.form_unsafe() == {}

    @pytest.mark.asyncio
    async def test_part_count_limit_enforced(self, monkeypatch):
        monkeypatch.setattr("renus.request.formparsers.MAX_FORM_PARTS", 3)
        fields = [(f"f{i}", "v") for i in range(4)]
        req = _make_request(
            [{"type": "http.request", "body": _multipart_body(fields), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data; boundary=bndry"),
            ],
        )
        with pytest.raises(RuntimeError, match="maximum"):
            await req.form_unsafe()

    @pytest.mark.asyncio
    async def test_malformed_part_skipped_without_crash(self):
        body = b"--bndry\r\ngarbage-without-header-block\r\n--bndry--\r\n"
        req = _make_request(
            [{"type": "http.request", "body": body, "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data; boundary=bndry"),
            ],
        )
        assert await req.form_unsafe() == {}

    @pytest.mark.asyncio
    async def test_upload_filename_kept_as_untrusted_metadata(self):
        # The declared filename is attacker-controlled metadata; the parser
        # must store it on the UploadFile without resolving it against the
        # filesystem (path traversal safety lives with the consumer, but the
        # parser itself must never write outside its own storage).
        body = _multipart_body([("f", "x")], boundary="bndry")
        body = body.replace(b'name="f"', b'name="f"; filename="../../etc/passwd"', 1)
        req = _make_request(
            [{"type": "http.request", "body": body, "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"content-type", b"multipart/form-data; boundary=bndry"),
            ],
        )
        form = await req.form_unsafe()
        upload = form["f"]
        assert upload.filename == "../../etc/passwd"


# --------------------------------------------------------------------------
# XSS sanitizer: tag vectors
# --------------------------------------------------------------------------


class TestXssTagBlocking:

    @pytest.mark.parametrize("tag", [
        "script", "iframe", "object", "embed", "form",
        "style", "base", "link", "applet", "meta",
    ])
    def test_dangerous_tags_rewritten(self, tag):
        out = _escape(f"<{tag}>x</{tag}>")
        # Blocked tags are rewritten to their plural block name; the
        # original singular tag must never survive as a tag.
        assert f"<{tag}" not in out
        assert f"&lt;{tag}&gt;" not in out

    def test_tag_blocking_is_case_insensitive(self):
        out = _escape("<ScRiPt>alert(1)</ScRiPt>")
        assert "<script" not in out
        assert "&lt;script&gt;" not in out

    def test_payload_content_kept_inert(self):
        out = _escape("<script>alert(1)</script>")
        assert "alert(1)" in out
        assert "<script" not in out

    def test_stray_close_tag_ignored(self):
        out = _escape("</script><b>hi</b>")
        assert "&lt;/script" not in out
        assert "&lt;b&gt;hi&lt;/b&gt;" in out


# --------------------------------------------------------------------------
# XSS sanitizer: attribute vectors
# --------------------------------------------------------------------------


class TestXssAttributeFiltering:

    @pytest.mark.parametrize(
        "payload,forbidden",
        [
            ('<img src="http://ok/x.png" onerror="alert(1)">', "onerror"),
            ("<svg onload=alert(1)>", "onload"),
            ('<a href="http://ok" onclick="alert(1)">x</a>', "onclick"),
            ("<body onpageshow=alert(1)>", "onpageshow"),
        ],
    )
    def test_event_handlers_stripped(self, payload, forbidden):
        out = _escape(payload)
        assert forbidden not in out

    def test_attribute_value_quote_breakout_neutralized(self):
        # A quote smuggled through entity encoding stays inside the escaped
        # attribute value; the output is display text, never executable
        # markup, so the handler cannot become a live attribute.
        out = _escape('<img alt="x&quot; onerror=&quot;alert(1)">')
        assert "<img" not in out
        assert "&lt;img" in out

    def test_allowed_attr_value_is_escaped(self):
        out = _escape("<img alt='&quot;><script>alert(1)</script>'>")
        assert "<script" not in out


# --------------------------------------------------------------------------
# XSS sanitizer: URL scheme vectors
# --------------------------------------------------------------------------


class TestXssUrlRewriting:

    def test_javascript_url_rewritten(self):
        out = _escape('<a href="javascript:alert(1)">x</a>')
        assert 'href="javascript:' not in out

    def test_javascript_url_case_bypass_rewritten(self):
        out = _escape('<a href="JaVaScRiPt:alert(1)">x</a>')
        assert 'href="JaVaScRiPt:' not in out

    def test_data_uri_rewritten(self):
        out = _escape('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>')
        assert 'href="data:' not in out

    def test_vbscript_uri_rewritten(self):
        out = _escape('<a href="vbscript:msgbox(1)">x</a>')
        assert 'href="vbscript:' not in out

    def test_protocol_relative_url_pinned_to_http(self):
        out = _escape('<a href="//evil.example">x</a>')
        assert 'href="//evil' not in out
        assert "http://evil.example" in out


# --------------------------------------------------------------------------
# XSS sanitizer: encoding/evasion vectors
# --------------------------------------------------------------------------


class TestXssEncodingEvasion:

    def test_double_encoded_entity_bypass_blocked(self):
        # Injection.escape unescapes first, so entity-encoded tags are
        # parsed as real tags and blocked like their literal form.
        out = Injection().escape("&lt;script&gt;alert(1)&lt;/script&gt;")
        assert "<script" not in out

    def test_hex_numeric_charref_dropped_by_sanitizer(self):
        out = _escape("&#x3C;script&#x3E;alert(1)")
        assert "<script" not in out

    def test_named_entity_passthrough_is_harmless(self):
        # Entities are decoded during parsing and re-escaped on output;
        # angle brackets can never reappear unescaped.
        out = _escape("a &amp; b &lt;tag&gt;")
        assert "a & b" in out
        assert "&lt;tag&gt;" in out
        assert "<tag>" not in out

    def test_injection_escape_strips_whitespace(self):
        assert Injection().escape("  <b>x</b>  ").startswith("&lt;")


# --------------------------------------------------------------------------
# Injection.protect: recursive structure sanitization
# --------------------------------------------------------------------------


class TestInjectionProtect:

    def test_nested_dict_and_list_sanitized(self):
        data = {"a": ["<script>x</script>", {"b": "<img src=x onerror=y>"}]}
        out = Injection().protect(data)
        assert "<script" not in out["a"][0]
        assert "onerror" not in out["a"][1]["b"]

    def test_dict_keys_escaped(self):
        out = Injection().protect({"<b>": "x"})
        (key, _) = next(iter(out.items()))
        assert "<b>" not in key

    def test_primitives_untouched(self):
        assert Injection().protect(3) == 3
        assert Injection().protect(True) is True
        assert Injection().protect(None) is None
        assert Injection().protect("3") == "3"


# --------------------------------------------------------------------------
# Host header trust: subdomain derivation
# --------------------------------------------------------------------------


class TestHostHeaderTrust:

    def test_subdomain_none_for_ip_literal_with_port(self):
        req = _make_request(headers=[(b"host", b"192.168.0.1:8080")])
        assert req.subdomain is None

    def test_subdomain_none_for_underscore_prefix(self):
        req = _make_request(headers=[(b"host", b"_.example.com")])
        assert req.subdomain is None

    def test_subdomain_case_normalized(self):
        req = _make_request(headers=[(b"host", b"API.Example.com")])
        assert req.subdomain == "api"

    def test_configured_host_exact_match_yields_no_subdomain(self, monkeypatch):
        def fake_get(self, name, *default):
            if name == "host":
                return "example.com"
            return default[0] if default else None

        monkeypatch.setattr(Config, "get", fake_get)
        monkeypatch.setattr(Config, "_cache", {})
        req = _make_request(headers=[(b"host", b"example.com")])
        assert req.subdomain is None

    def test_configured_host_suffix_confusion_rejected(self, monkeypatch):
        # "evilexample.com" must not be treated as a subdomain of
        # "example.com" (dot-boundary check).
        def fake_get(self, name, *default):
            if name == "host":
                return "example.com"
            return default[0] if default else None

        monkeypatch.setattr(Config, "get", fake_get)
        monkeypatch.setattr(Config, "_cache", {})
        req = _make_request(headers=[(b"host", b"evilexample.com")])
        assert req.subdomain is None

    def test_configured_host_with_scheme_and_port_normalized(self, monkeypatch):
        def fake_get(self, name, *default):
            if name == "host":
                return "https://example.com:8443"
            return default[0] if default else None

        monkeypatch.setattr(Config, "get", fake_get)
        monkeypatch.setattr(Config, "_cache", {})
        req = _make_request(headers=[(b"host", b"api.example.com")])
        assert req.subdomain == "api"

    def test_host_header_control_chars_sanitized_before_use(self):
        # A Host header cannot smuggle a second header through its value.
        req = _make_request(headers=[(b"host", b"example.com\r\nX-Evil: 1")])
        assert "\r" not in req.headers["host"]
        assert "\n" not in req.headers["host"]


# --------------------------------------------------------------------------
# Encrypted body: fail-closed behavior
# --------------------------------------------------------------------------


class _ReversingCryptor:

    def __init__(self, request):
        self.request = request

    def decrypt_text(self, text):
        return text[::-1]


class _ExplodingCryptor:

    def __init__(self, request):
        self.request = request

    def decrypt_text(self, text):
        raise ValueError("bad ciphertext")


class TestEncryptedBodyFailClosed:

    @pytest.mark.asyncio
    async def test_garbage_ciphertext_raises_and_leaks_nothing(self, monkeypatch):
        monkeypatch.setattr(Request, "cryptor", _ExplodingCryptor)
        req = _make_request(
            [{"type": "http.request", "body": b"attacker-controlled-bytes", "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"encrypted", b"1"),
                (b"real-type", b"application/json"),
            ],
        )
        with pytest.raises(ValueError, match="Failed to decrypt"):
            await req.form_unsafe()

    @pytest.mark.asyncio
    async def test_encrypted_header_must_be_exact_match(self):
        # "encrypted: 0" must not trigger the decryption path.
        req = _make_request(
            [{"type": "http.request", "body": b'{"a": 1}', "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"encrypted", b"0"),
                (b"content-type", b"application/json"),
            ],
        )
        assert await req.form_unsafe() == {"a": 1}

    @pytest.mark.asyncio
    async def test_real_type_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(Request, "cryptor", _ReversingCryptor)
        body = '{"a": 1}'[::-1]
        req = _make_request(
            [{"type": "http.request", "body": body.encode(), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"encrypted", b"1"),
                (b"real-type", b"Application/JSON"),
            ],
        )
        assert await req.form_unsafe() == {"a": 1}

    @pytest.mark.asyncio
    async def test_decrypted_payload_still_sanitized_by_form(self, monkeypatch):
        monkeypatch.setattr(Request, "cryptor", _ReversingCryptor)
        body = '{"x": "<script>alert(1)</script>"}'[::-1]
        req = _make_request(
            [{"type": "http.request", "body": body.encode(), "more_body": False}],
            headers=[
                (b"host", b"example.com"),
                (b"encrypted", b"1"),
                (b"real-type", b"application/json"),
            ],
        )
        form = await req.form()
        assert "<script" not in form["x"]

    @pytest.mark.asyncio
    async def test_no_cryptor_configured_fails_closed(self):
        Request.cryptor = None
        req = _make_request(
            [{"type": "http.request", "body": b"xyz", "more_body": False}],
            headers=[(b"host", b"example.com"), (b"encrypted", b"1")],
        )
        with pytest.raises(ValueError):
            await req.form_unsafe()
