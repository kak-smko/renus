import html
import json
import re
import typing
from http import cookies as http_cookies
from urllib.parse import parse_qsl

from multipart.multipart import parse_options_header

from renus.core.config import Config
from renus.core.formparsers import FormParser, MultiPartParser
from renus.core.injection import Injection


class Request:
    def __init__(self, scope, receive) -> None:
        self._scope = scope
        self._receive = receive
        self._headers = headers_parser(self._scope.get('headers', []))
        self._stream_consumed = False
        self.inputs = {}
        self.route = {}

    @property
    def headers(self) -> dict:
        return self._headers

    @property
    def cookies(self):
        if not hasattr(self, "_cookies"):
            headers = self.headers
            self._cookies = {}
            if 'cookie' in headers:
                self._cookies = cookie_parser(headers['cookie'])

        return self._cookies

    @property
    def client(self):
        return self._scope.get("client", [])

    @property
    def ip(self):
        return self.headers.get(Config('app').get('ipHeader', False), self.client[0])

    @property
    def sub_domain(self):
        if not hasattr(self, "_sub_domain"):
            host = self.headers.get('host', None)
            if host is None:
                return None

            ip = re.findall(r'[0-9]+(?:\.[0-9]+){3}', host)
            if len(ip) != 0:
                return None
            r = host.split('.')

            if len(r) <= 1:
                return None
            if len(r) == 2:
                if r[1].split(':')[0] == 'localhost':
                    return r[0]
                else:
                    return None
            self._sub_domain = r[0]

        return self._sub_domain

    @property
    def user_agent(self):
        return self.headers.get("user-agent", None)

    @property
    def base_path(self):
        if not hasattr(self, "_base_path"):
            headers = self.headers
            scheme = self._scope.get("scheme", "http")
            server = self._scope.get("server", None)
            host_header = None
            if 'host' in headers:
                host_header = headers['host']

            if host_header is not None:
                url = f"{scheme}://{host_header}"
            elif server is None:
                url = ''
            else:
                host, port = server
                default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
                if port == default_port:
                    url = f"{scheme}://{host}"
                else:
                    url = f"{scheme}://{host}:{port}"

            self._base_path = url

        return self._base_path

    @property
    def full_path(self):
        if not hasattr(self, "_full_path"):
            path = self._scope.get("root_path", "") + self._scope.get("path", "")
            query_string = self._scope.get("query_string", b"")
            url = self.base_path
            url += path
            if query_string:
                url += "?" + query_string.decode()
            self._full_path = url

        return self._full_path

    @property
    def query_params(self):
        if not hasattr(self, "_query_params"):
            self._query_params = query_parser(self._scope.get('query_string', ''))
        return self._query_params

    @property
    def method(self) -> str:
        return self._scope.get("method", '')

    async def stream(self) -> typing.AsyncGenerator[bytes, None]:
        if hasattr(self, "_body"):
            yield self._body
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
        if not hasattr(self, "_body"):
            chunks = []
            async for chunk in self.stream():
                chunks.append(chunk)
            self._body = b"".join(chunks)
        return self._body

    async def form(self):
        if not hasattr(self, "_form"):
            content_type_header = self.headers.get("content-type")
            content_type, options = parse_options_header(content_type_header)
            if content_type == b"multipart/form-data":
                multipart_parser = MultiPartParser(self.headers, self.stream())
                self._form = await multipart_parser.parse()
            elif content_type in [b"app/x-www-form-urlencoded", b"application/x-www-form-urlencoded"]:
                form_parser = FormParser(self.headers, self.stream())
                self._form = await form_parser.parse()
            else:
                body = await self.body()
                try:
                    self._form = {} if body == b"" else json.loads(body)
                except Exception:
                    self._form = {}

                self._form = Injection().protect(self._form)

        return self._form


def headers_parser(headers: list) -> typing.Dict[str, str]:
    headers_dict: typing.Dict[str, str] = {}
    for header in headers:
        headers_dict[html.escape(str(header[0].decode("utf-8")).lower())] = html.escape(header[1].decode("utf-8"))

    return headers_dict


def cookie_parser(cookie_string: str) -> typing.Dict[str, str]:
    cookie_dict: typing.Dict[str, str] = {}
    cookie_string = html.escape(cookie_string)
    for chunk in cookie_string.split(";"):
        if "=" in chunk:
            key, val = chunk.split("=", 1)
        else:
            key, val = "", chunk
        key, val = key.strip(), val.strip()
        if key or val:
            cookie_dict[key] = http_cookies._unquote(val)
    return cookie_dict


def query_parser(query_string: str):
    params = parse_qsl(query_string.decode("utf-8"), keep_blank_values=True)
    params = {k: v for k, v in params}
    params = Injection().protect(params)
    return params


class ClientDisconnect(Exception):
    pass
