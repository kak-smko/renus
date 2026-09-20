from __future__ import annotations

import re
import types
import typing
from urllib.parse import parse_qsl

from renus.config import Config
from renus.datastructures import FormData, UploadFile
from renus.request.exceptions import ClientDisconnect
from renus.request.formparsers import FormParser, MultiPartParser
from renus.request.injection import Injection
from renus.request.limits import MAX_BODY_SIZE
from renus.request.options import parse_options_header
from renus.request.parsers import cookie_parser, headers_parser, query_parser
from renus.util.codec import json_decode

_UNSET = types.SimpleNamespace()

_IP_LITERAL_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3}(?::[0-9]+)?$")


class Request:
    """Represent an incoming HTTP request."""

    cryptor = None

    _injection = Injection()

    def __init__(self, scope: dict, receive: typing.Callable) -> None:
        """Create a request from an ASGI scope and receive callable.

        Parameters
        ----------
        scope:
            ASGI connection scope describing the request.
        receive:
            Async callable delivering incoming request messages.
        """
        self._scope: dict = scope
        self._receive: typing.Callable = receive
        self._headers: dict[str, str] | object = _UNSET

        self._stream_consumed: bool = False
        self._is_disconnected: bool = False

        self._cookies: dict[str, str] | object = _UNSET
        self._subdomain: str | None | object = _UNSET
        self._base_path: str | object = _UNSET
        self._full_path: str | object = _UNSET
        self._query_params: dict[str, str] | object = _UNSET
        self._body: bytes | object = _UNSET
        self._form: FormData | object = _UNSET
        self._form_safe: FormData | object = _UNSET
        self.route: dict = {}
        self.state: dict = {"app": scope.get("app")}

    def __getattr__(self, name: str) -> typing.Any:

        if self.state["app"] and name in self.state["app"].state:
            return self.state["app"].state[name]
        if name in self.state:
            return self.state[name]
        raise AttributeError(
            f"Request has no attribute {name!r} and {name!r} is not in request.state"
        )

    @property
    def headers(self) -> dict[str, str]:
        """Request headers as a lowercase name-to-value mapping."""
        if self._headers is _UNSET:
            self._headers = headers_parser(self._scope.get("headers", []))
        return typing.cast(dict[str, str], self._headers)

    @property
    def cookies(self) -> dict[str, str]:
        """Parsed request cookies."""
        if self._cookies is _UNSET:
            header = self.headers.get("cookie")
            self._cookies = cookie_parser(header) if header else {}
        return typing.cast(dict[str, str], self._cookies)

    @property
    def client(self) -> list:
        """Client host and port information from the scope."""
        return self._scope.get("client", [])

    @property
    def ip(self) -> typing.Optional[str]:
        """Client IP address, honoring the configured IP header if set."""
        header = Config("app").get("ipHeader", False)
        header = Config("app").get("ipHeader", False)
        if header:
            return self.headers.get(header)
        return self.client[0] if self.client else None

    @property
    def subdomain(self) -> typing.Optional[str]:
        """First label of the host header, or ``None`` for bare hosts."""
        if self._subdomain is _UNSET:
            host = self.headers.get("host")
            if host is None or _IP_LITERAL_RE.match(host) or host.count(".") == 0:
                self._subdomain = None
            else:
                self._subdomain = host.split(".")[0]
        return typing.cast(typing.Optional[str], self._subdomain)

    @property
    def user_agent(self) -> typing.Optional[str]:
        """Value of the ``user-agent`` header."""
        return self.headers.get("user-agent")

    @property
    def url(self) -> str:
        """Full request URL, alias for :attr:`full_path`."""
        return self.full_path

    @property
    def base_path(self) -> str:
        """Scheme, host and port portion of the request URL."""
        if self._base_path is _UNSET:
            scheme = self._scope.get("scheme", "http")
            server = self._scope.get("server")
            host_header = self.headers.get("host")

            if host_header is not None:
                url = f"{scheme}://{host_header}"
            elif server is None:
                url = ""
            else:
                host, port = server
                default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
                url = (
                    f"{scheme}://{host}"
                    if port == default_port
                    else f"{scheme}://{host}:{port}"
                )

            self._base_path = url

        return typing.cast(str, self._base_path)

    @property
    def full_path(self) -> str:
        """Full request URL including path and query string."""
        if self._full_path is _UNSET:
            path = self._scope.get("root_path", "") + self._scope.get("path", "")
            query_string = self._scope.get("query_string", b"")

            url = self.base_path + path
            if query_string:
                url += "?" + query_string.decode("utf-8", errors="replace")
            self._full_path = url

        return typing.cast(str, self._full_path)

    @property
    def query_params(self) -> dict[str, str]:
        """Parsed query-string parameters."""
        if self._query_params is _UNSET:
            self._query_params = query_parser(self._scope.get("query_string", b""))
        return typing.cast(dict[str, str], self._query_params)

    @property
    def method(self) -> str:
        """Uppercased HTTP method of the request."""
        return self._scope.get("method", "").upper()

    async def stream(self) -> typing.AsyncGenerator[bytes, None]:
        """Yield the request body as chunks."""
        if self._body is not _UNSET:
            yield typing.cast(bytes, self._body)
            yield b""
            return

        if self._stream_consumed:
            raise RuntimeError("Stream consumed")
        self._stream_consumed = True

        while True:
            message = await self._receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body:
                    yield body
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                self._is_disconnected = True
                raise ClientDisconnect()

        yield b""

    async def body(self) -> bytes:
        """Read and return the full request body."""
        if self._body is _UNSET:
            chunks: list[bytes] = []
            total_size = 0
            async for chunk in self.stream():
                total_size += len(chunk)
                if total_size > MAX_BODY_SIZE:
                    raise RuntimeError("Request body too large")
                chunks.append(chunk)
            self._body = b"".join(chunks)

        return typing.cast(bytes, self._body)

    async def form_unsafe(self) -> FormData:
        """Parse and return the request body as form data."""
        if self._form is _UNSET:
            content_type_value = self.headers.get("content-type", "")
            content_type, _ = parse_options_header(content_type_value)

            if self._is_encrypted():
                raw_body = await self.body()
                self._form = self._to_form_data(self._decrypt_body(raw_body))
            elif content_type == "multipart/form-data":
                parser = MultiPartParser(self.headers, self.stream())
                self._form = await parser.parse()
            elif content_type in (
                "app/x-www-form-urlencoded",
                "application/x-www-form-urlencoded",
            ):
                parser = FormParser(self.headers, self.stream())
                self._form = await parser.parse()
            else:
                body = await self.body()
                data = {} if body == b"" else json_decode(body)
                self._form = self._to_form_data(data)

        return typing.cast(FormData, self._form)

    async def form(self) -> FormData:
        """Parse the form and return XSS-sanitized form data."""
        if self._form_safe is _UNSET:
            unsafe = await self.form_unsafe()
            items = [
                (
                    key,
                    value
                    if isinstance(value, UploadFile)
                    else self._injection.protect(value),
                )
                for key, value in unsafe.multi_items()
            ]
            self._form_safe = FormData(typing.cast(typing.Any, items))
        return typing.cast(FormData, self._form_safe)

    def _to_form_data(self, data: typing.Any) -> FormData:
        """Coerce parsed body data into a ``FormData`` mapping."""
        if isinstance(data, FormData):
            return data
        if isinstance(data, dict):
            return FormData(data)
        return FormData([])

    def _is_encrypted(self) -> bool:
        return self.headers.get("encrypted", "") == "1"

    def _get_real_content_type(self) -> str:
        return self.headers.get("real-type", "application/json")

    def _decrypt_body(self, body: bytes) -> typing.Any:
        if self.cryptor is None:
            raise ValueError(
                "Cannot decrypt encrypted request body: no cryptor configured"
            )

        try:
            decrypted = self.cryptor(request=self).decrypt_text(
                body.decode("utf-8").strip()
            )
        except Exception as exc:
            raise ValueError(f"Failed to decrypt request body: {exc}") from exc

        real_type = self._get_real_content_type().lower()
        if "application/json" in real_type:
            return json_decode(decrypted)
        if "application/x-www-form-urlencoded" in real_type:
            return dict(parse_qsl(decrypted, keep_blank_values=True))
        return decrypted

