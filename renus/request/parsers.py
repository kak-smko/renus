from __future__ import annotations

import re
import typing
from urllib.parse import parse_qsl

from renus.request.limits import (
    MAX_COOKIES,
    MAX_COOKIE_SIZE,
    MAX_HEADERS,
    MAX_HEADER_SIZE,
    MAX_QUERY_SIZE,
)

_VALID_HEADER_NAME_RE = re.compile(r"^[a-zA-Z0-9!#$%&'*+\-.^_`|~]+$")

def _build_header_clean_trans() -> dict:

    return {**{c: None for c in range(0x00, 0x09)}, **{c: None for c in range(0x0A, 0x20)}, 0x7F: None}

_HEADER_CLEAN_TRANS = _build_header_clean_trans()

def _sanitize_header_value(value: str) -> str:
    return value.translate(_HEADER_CLEAN_TRANS)

def _pure_headers_parser(headers: typing.List[typing.Tuple[bytes, bytes]]) -> typing.Dict[str, str]:
    """Parse raw header pairs into a lowercase name-to-value mapping."""
    if len(headers) > MAX_HEADERS:
        raise RuntimeError("Too many headers")

    parsed: typing.Dict[str, str] = {}
    for name_bytes, value_bytes in headers:
        try:
            name = name_bytes.decode("utf-8").lower()
        except UnicodeDecodeError:
            continue

        if not _VALID_HEADER_NAME_RE.match(name):
            continue

        try:
            raw_value = value_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_value = value_bytes.decode("utf-8", errors="replace")

        if len(raw_value) > MAX_HEADER_SIZE:
            raise RuntimeError("Header too large")

        parsed[name] = _sanitize_header_value(raw_value)

    return parsed

def _unquote_cookie_value(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1].replace("\\\\", "\\").replace('\\"', '"')
    return value

def cookie_parser(cookie_string: str) -> typing.Dict[str, str]:
    """Parse a cookie header string into a name-to-value mapping."""
    if len(cookie_string) > MAX_COOKIE_SIZE:
        raise RuntimeError("Cookie too large")

    chunks = cookie_string.split(";")[:MAX_COOKIES]
    cookies: typing.Dict[str, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        key, _, value = chunk.partition("=")
        key = key.strip().translate(_HEADER_CLEAN_TRANS)
        value = value.strip().translate(_HEADER_CLEAN_TRANS)
        if key:
            cookies[key] = _unquote_cookie_value(value)

    return cookies

def query_parser(query_string: bytes) -> typing.Dict[str, str]:
    """Parse a URL query string into a name-to-value mapping."""
    if len(query_string) > MAX_QUERY_SIZE:
        raise RuntimeError("Query too large")

    params = parse_qsl(query_string.decode("utf-8"), keep_blank_values=True)
    cleaned: typing.Dict[str, str] = {}
    for name, value in params:
        name = name.translate(_HEADER_CLEAN_TRANS)
        if not name:
            continue
        cleaned[name] = value.translate(_HEADER_CLEAN_TRANS)

    return cleaned

try:
    from renus._speedup import (
        cookie_parser as _fast_cookie_parser,
        headers_parser as _fast_headers_parser,
        query_parser as _fast_query_parser,
    )
    headers_parser = _fast_headers_parser
    cookie_parser = _fast_cookie_parser
    query_parser = _fast_query_parser
except ImportError:
    headers_parser = _pure_headers_parser
