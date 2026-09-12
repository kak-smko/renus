# cython: language_level=3
# cython: boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated ASGI header parsing.

Implements the same contract as ``renus.request.parsers.headers_parser`` but
skips the two dominant pure-Python costs on clean ASCII headers:

- the per-header ``re`` token validation (replaced by a raw-byte table scan), and
- the per-value ``str.translate`` (only applied when the value actually
  contains a stripped control character, detected by a C byte scan).

The module is optional: ``renus.request.parsers`` falls back to the pure-Python
implementation when this compiled module is unavailable.
"""

from libc.stdlib cimport free, malloc

from cpython.bytes cimport PyBytes_AS_STRING, PyBytes_GET_SIZE

from renus.request.limits import (
    MAX_COOKIES,
    MAX_COOKIE_SIZE,
    MAX_HEADERS,
    MAX_HEADER_SIZE,
    MAX_QUERY_SIZE,
)

# Sentinel the pure-Python module builds; kept local here to avoid a circular
# import (``renus.request.parsers`` imports this module).
# Nullify 0x00-0x08 and 0x0A-0x1F (everything under space but tab), plus DEL.
cdef dict _HEADER_CLEAN_TRANS = {
    **{c: None for c in range(0x00, 0x09)},
    **{c: None for c in range(0x0A, 0x20)},
    0x7F: None,
}

#: RFC7230 ``token`` bytes (same alphabet as the pure-Python regex).
cdef unsigned char _TOKEN[256]


def _init_token():
    cdef int i
    for i in range(256):
        _TOKEN[i] = 0
    for ch in b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
        _TOKEN[<int>ch] = 1


_init_token()


cdef inline int _stripped(unsigned int c) noexcept:
    return (c < 32 and c != 9) or c == 127


def headers_parser(headers):
    """Decode an ASGI ``headers`` list into a lowercase-name ``dict``."""
    if len(headers) > MAX_HEADERS:
        raise RuntimeError("Too many headers")

    cdef dict parsed = {}
    cdef bytes nameb, valb
    cdef str name, val
    cdef Py_ssize_t i, vlen, k
    cdef const unsigned char* vbuf
    cdef int clean

    for i in range(len(headers)):
        nameb, valb = headers[i]

        # Header-name token validation via raw-byte scan (no regex).
        vbuf = <const unsigned char*>PyBytes_AS_STRING(nameb)
        vlen = PyBytes_GET_SIZE(nameb)
        clean = vlen > 0
        for k in range(vlen):
            if not _TOKEN[vbuf[k]]:
                clean = 0
                break
        if not clean:
            continue

        try:
            name = nameb.decode("ascii")
        except UnicodeDecodeError:
            continue
        name = name.lower()

        try:
            val = valb.decode("utf-8")
        except UnicodeDecodeError:
            val = valb.decode("utf-8", "replace")

        if len(val) > MAX_HEADER_SIZE:
            raise RuntimeError("Header too large")

        # Detect stripped control characters over the raw bytes; only translate
        # when the value is actually dirty (the overwhelmingly common clean case
        # avoids ``str.translate`` entirely).
        vbuf = <const unsigned char*>PyBytes_AS_STRING(valb)
        vlen = PyBytes_GET_SIZE(valb)
        clean = 1
        for k in range(vlen):
            if _stripped(vbuf[k]):
                clean = 0
                break
        if not clean:
            val = val.translate(_HEADER_CLEAN_TRANS)

        parsed[name] = val

    return parsed


cdef str _unquote_cookie_value(str value) noexcept:
    """Unwrap a quoted cookie value, honoring ``\\`` and ``\"`` escapes."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace("\\\\", "\\").replace('\\"', '"')
    return value


def cookie_parser(cookie_string: str):
    """Parse a raw ``Cookie`` header into a ``{name: value}`` dict.

    Raises ``RuntimeError`` if the header exceeds ``MAX_COOKIE_SIZE``.
    """
    if len(cookie_string) > MAX_COOKIE_SIZE:
        raise RuntimeError("Cookie too large")

    cdef list chunks = cookie_string.split(";")[:MAX_COOKIES]
    cdef dict cookies = {}
    cdef str chunk, key, value
    cdef Py_ssize_t pos, i

    for i in range(len(chunks)):
        chunk = chunks[i].strip()
        if not chunk:
            continue

        pos = chunk.find("=")
        if pos == -1:
            key = chunk
            value = ""
        else:
            key = chunk[:pos]
            value = chunk[pos + 1:]

        key = key.strip().translate(_HEADER_CLEAN_TRANS)
        if not key:
            continue
        value = value.strip().translate(_HEADER_CLEAN_TRANS)

        cookies[key] = _unquote_cookie_value(value)

    return cookies


cdef inline int _is_hex(unsigned int c) noexcept:
    return (c >= 48 and c <= 57) or (c >= 65 and c <= 70) or (c >= 97 and c <= 102)


cdef inline unsigned int _hex_val(unsigned int c) noexcept:
    if c <= 57:
        return c - 48
    if c >= 97:
        return c - 87
    return c - 55


cdef str _qdecode(const unsigned char* p, Py_ssize_t s, Py_ssize_t e):
    """Decode ``&``-split behaviour plus percent-escapes into a clean str.

    Mirrors ``urllib.parse.unquote`` semantics on the sub-range ``[s, e)``:
    ``+`` becomes space, valid ``%XX`` escapes are decoded, and disallowed
    control characters are dropped (the same cleaning the pure-Python
    ``query_parser`` applies with ``str.translate``).
    """
    cdef Py_ssize_t n = e - s, oi = 0, i
    if n <= 0:
        return ""
    cdef unsigned char* out = <unsigned char*>malloc(n)
    if out == NULL:
        raise MemoryError()

    i = s
    while i < e:
        c = p[i]
        if c == 37 and i + 2 < e and _is_hex(p[i + 1]) and _is_hex(p[i + 2]):
            d = (_hex_val(p[i + 1]) << 4) | _hex_val(p[i + 2])
            if not _stripped(d):
                out[oi] = d
                oi += 1
            i += 3
        elif c == 43:  # '+'
            out[oi] = 32
            oi += 1
            i += 1
        elif _stripped(c):
            i += 1
        else:
            out[oi] = c
            oi += 1
            i += 1

    try:
        return (<bytes>out[:oi]).decode("utf-8", "replace")
    finally:
        free(out)


def query_parser(query_string: bytes):
    """Parse the raw ASGI ``query_string`` bytes into a ``{name: value}`` dict.

    Raises ``RuntimeError`` if the query exceeds ``MAX_QUERY_SIZE``.
    """
    if len(query_string) > MAX_QUERY_SIZE:
        raise RuntimeError("Query too large")

    cdef const unsigned char* p = <const unsigned char*>PyBytes_AS_STRING(query_string)
    cdef Py_ssize_t n = PyBytes_GET_SIZE(query_string)
    cdef dict out = {}
    cdef str name, value
    cdef Py_ssize_t start = 0, i = 0, j

    while i <= n:
        if i == n or p[i] == 38:  # '&'
            if i > start:
                j = start
                while j < i and p[j] != 61:  # '='
                    j += 1
                if j < i:
                    name = _qdecode(p, start, j)
                    value = _qdecode(p, j + 1, i)
                else:
                    name = _qdecode(p, start, i)
                    value = ""
                if name:
                    out[name] = value
            start = i + 1
        i += 1

    return out
