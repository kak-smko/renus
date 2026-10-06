from __future__ import annotations

import http.cookies
from functools import lru_cache
from typing import Any, Mapping, Optional

from renus.datastructures import Background
from renus.response.gzip import GZIP_MIN_LENGTH, GzipStreamer
from renus.response.status import Status

_CONTENT_ENCODING_NONE = b"none"
_CONTENT_ENCODING_GZIP = b"gzip"
_FORBIDDEN_HEADER_CHARS = ("\r", "\n", "\0")

def _validate_header_value(name: str, value: str) -> None:
    """Reject header/cookie values that could split HTTP headers."""
    if any(c in value for c in _FORBIDDEN_HEADER_CHARS):
        raise ValueError(
            f"Header value for {name!r} contains illegal control characters"
        )

@lru_cache(maxsize=64)
def _encode_content_type(media_type: str, charset: str) -> bytes:
    if media_type.startswith("text/"):
        media_type = f"{media_type}; charset={charset}"
    return media_type.encode("utf-8")

class Response:
    """Base class for all HTTP responses.

    Renders body content, builds raw headers, and streams the response over
    the ASGI interface, with optional content encryption and gzip encoding.
    """

    media_type = "text/html"
    charset = "utf-8"
    cryptor = None

    def __init__(
        self,
        content: Any = None,
        status_code: Status = Status.HTTP_200_OK,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[Background] = None,
        cryptor: Optional[Any] = None,
    ) -> None:
        """Initialize the response.

        Parameters
        ----------
        content:
            Body content to render into bytes.
        status_code:
            HTTP status code for the response.
        headers:
            Optional mapping of initial response headers.
        media_type:
            Response media type. Defaults to the class ``media_type``.
        background:
            Optional task to run after the response is sent.
        cryptor:
            Optional callable used to encrypt the response body.
        """
        self.status_code = status_code
        if media_type is not None:
            self.media_type = media_type

        self.encrypt = False
        if cryptor is not None:
            self.cryptor = cryptor
        if self.cryptor:
            self.encrypt = True

        self.body = self.render(content)
        self.raw_headers: list[tuple[bytes, bytes]] = []
        self.init_headers(headers)
        self.background = background

    def __repr__(self) -> str:
        """Return a string representation of the response."""
        return (f"{self.__class__.__name__}(status_code={self.status_code}, "
                f"media_type={self.media_type!r})")

    def render(self, content: Any) -> bytes:
        """Return ``content`` encoded as bytes for the response body."""
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def init_headers(self, headers: Optional[Mapping[str, str]] = None) -> None:
        """Build the raw response headers.

        Parameters
        ----------
        headers:
            Optional user-supplied headers merged with the computed ones.
        """
        content_type = self.media_type

        if headers is None and not self.encrypt:
            self.raw_headers = (
                []
                if content_type is None
                else [(b"content-type", _encode_content_type(content_type, self.charset))]
            )
            return

        populate_content_type = True
        raw_headers: list[tuple[bytes, bytes]] = []

        if headers is not None:
            for key, value in headers.items():
                lower_key = key.lower()
                _validate_header_value(lower_key, value)
                if lower_key !="content-length":
                    encoded_value = value.encode("utf-8")
                    if self.encrypt and lower_key == "content-type":
                        raw_headers.append((b"real-type", encoded_value))
                    else:
                        raw_headers.append((lower_key.encode("utf-8"), encoded_value))
                if lower_key == "content-type":
                    populate_content_type = False

        if content_type is not None and populate_content_type:
            ct_bytes = _encode_content_type(content_type, self.charset)
            if self.encrypt:
                raw_headers.append((b"real-type", ct_bytes))
            else:
                raw_headers.append((b"content-type", ct_bytes))

        if self.encrypt:
            raw_headers.append((b"encrypted", b"1"))
            raw_headers.append((b"content-type", b"application/octet-stream"))
            raw_headers.append((b"access-control-expose-headers", b"encrypted,real-type"))
        self.raw_headers = raw_headers

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: Optional[int] = None,
        expires: Optional[int] = None,
        path: str = "/",
        domain: Optional[str] = None,
        secure: bool = True,
        httponly: bool = True,
        samesite: str = "lax",
    ) -> None:
        """Set a cookie on the response.
        """
        _validate_header_value(key, key)
        _validate_header_value(key, value)
        cookie = http.cookies.SimpleCookie()
        cookie[key] = value
        if max_age is not None:
            cookie[key]["max-age"] = max_age
        if expires is not None:
            cookie[key]["expires"] = expires
        if path is not None:
            cookie[key]["path"] = path
        if domain is not None:
            cookie[key]["domain"] = domain
        if secure:
            cookie[key]["secure"] = True
        if httponly:
            cookie[key]["httponly"] = True
        if samesite is not None:
            if samesite.lower() not in ("strict", "lax", "none"):
                raise ValueError("samesite must be either 'strict', 'lax' or 'none'")
            cookie[key]["samesite"] = samesite
        self.raw_headers.append(
            (b"set-cookie", cookie.output(header="").strip().encode("utf-8"))
        )

    def delete_cookie(
        self, key: str, path: str = "/", domain: Optional[str] = None
    ) -> None:
        """Expire the cookie identified by ``key``."""
        self.set_cookie(key, expires=0, max_age=0, path=path, domain=domain)

    async def __call__(self, request, scope, receive, send) -> None:
        """Encode and send the response over the ASGI interface."""
        body = self.body
        raw_headers = self.raw_headers

        accepts_gzip = False
        if len(body) > GZIP_MIN_LENGTH:
            request_headers = scope.get("headers") if scope else None
            if request_headers is not None:
                for name, value in request_headers:
                    if name.lower() == b"accept-encoding":
                        accepts_gzip = b"gzip" in value
                        break
            else:
                accepts_gzip = "gzip" in request.headers.get("accept-encoding", "")

        if self.encrypt:

            body = self.cryptor(request=request).encrypt(body)
        if accepts_gzip and len(body) > GZIP_MIN_LENGTH:
            gzip_streamer = GzipStreamer()
            body = gzip_streamer.write(body) + gzip_streamer.finish()
            content_encoding = _CONTENT_ENCODING_GZIP
        else:
            content_encoding = _CONTENT_ENCODING_NONE

        response_headers = [
            *raw_headers,
            (b"content-encoding", content_encoding),
            (b"content-length", str(len(body)).encode("utf-8")),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": body})

        if self.background is not None:
            await self.background()
