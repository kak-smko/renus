import copy
import json
import re
import typing
from urllib.parse import parse_qsl

from multipart.multipart import parse_options_header

from renus.core.config import Config
from renus.core.formparsers import FormParser, MultiPartParser
from renus.core.injection import Injection

MAX_BODY_SIZE=Config('app').get('max_body_size',10 * 1024 * 1024)
MAX_HEADERS=Config('app').get('max_headers',100)
MAX_HEADER_SIZE=Config('app').get('max_headers_size',8192)
MAX_COOKIES=Config('app').get('max_cookies',50)
MAX_COOKIE_SIZE=Config('app').get('max_cookies_size',4096)
MAX_QUERY_SIZE=Config('app').get('max_query_size',1024)
class Request:
    cryptor = None

    def __init__(self, scope, receive) -> None:
        self._scope = scope
        self._receive = receive
        self._headers = headers_parser(self._scope.get('headers', []))
        self._stream_consumed = False
        self.inputs = {}
        self.route = {}
        self.state = {}

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
    def subdomain(self):
        if not hasattr(self, "_subdomain"):
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
            self._subdomain = r[0]

        return self._subdomain

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

    def _is_encrypted(self) -> bool:
        return self.headers.get('encrypted', '') == '1'

    def _get_real_content_type(self) -> str:
        return self.headers.get('real-type', 'application/json')

    def _decrypt_body(self, body: bytes) -> typing.Any:
        try:
            decrypted_text = self.cryptor(request=self).decrypt_text(body.decode('utf-8').strip())
            real_type = self._get_real_content_type().lower()

            if 'application/json' in real_type:
                return json.loads(decrypted_text)
            elif 'application/x-www-form-urlencoded' in real_type:
                return dict(parse_qsl(decrypted_text, keep_blank_values=True))
            else:
                return decrypted_text

        except Exception as e:
            raise ValueError(f"Failed to decrypt request body: {e}")

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
            total_size = 0
            async for chunk in self.stream():
                total_size += len(chunk)
                if total_size > MAX_BODY_SIZE:
                    raise RuntimeError("Request body too large")
                           
                chunks.append(chunk)
            self._body = b"".join(chunks)

        return self._body

    async def form(self):
        if not hasattr(self, "_form"):
            content_type_header = self.headers.get("content-type", "")
            content_type, options = parse_options_header(content_type_header)

            if self._is_encrypted():
                raw_body = await self.body()
                self._form = self._decrypt_body(raw_body)
            elif content_type == b"multipart/form-data":
                multipart_parser = MultiPartParser(self.headers, self.stream())
                self._form = await multipart_parser.parse()
            elif content_type in [b"app/x-www-form-urlencoded", b"application/x-www-form-urlencoded"]:
                form_parser = FormParser(self.headers, self.stream())
                self._form = dict(await form_parser.parse())
            else:
                body = await self.body()
                try:
                    self._form = {} if body == b"" else json.loads(body)
                except Exception:
                    self._form = {}

        return self._form

    async def form_safe(self):
        if not hasattr(self, "_form_safe"):
            self._form_safe = await self.form()
            if isinstance(self._form_safe, dict):
                self._form_safe = Injection().protect(copy.deepcopy(self._form_safe))
            self.inputs = self._form_safe
        return self._form_safe


_VALID_HEADER_NAME_RE = re.compile(r'^[a-zA-Z0-9!#$%&\'*+\-.^_`|~]+$')

def _sanitize_header_value(value: str) -> str:
    return value.translate(_HEADER_CLEAN_TRANS)


def _build_header_clean_trans() -> dict:
    trans = {}
    for c in range(0x00, 0x09):
        trans[c] = None   

    for c in range(0x0A, 0x20):
        trans[c] = None      
    trans[0x7F] = None      
    return {k: None for k in range(0x00, 0x20)} | {0x7F: None} | {0x09: 0x09}


_HEADER_CLEAN_TRANS = _build_header_clean_trans()


def headers_parser(headers: list) -> typing.Dict[str, str]:
    if len(headers) > MAX_HEADERS:
        raise RuntimeError("Too many headers")
    headers_dict: typing.Dict[str, str] = {}
    for header in headers:
        try:
            name = header[0].decode("utf-8").lower()
        except UnicodeDecodeError:
            continue
            
        if not _VALID_HEADER_NAME_RE.match(name):
            continue
            
        try:
            raw_value = header[1].decode("utf-8")
        except UnicodeDecodeError:
            raw_value = header[1].decode("utf-8", errors="replace")
        if len(raw_value) > MAX_HEADER_SIZE:
            raise RuntimeError("Header too large")
                    
        value = raw_value.translate(_HEADER_CLEAN_TRANS)

        headers_dict[name] = value

    return headers_dict



def _unquote_cookie_value(value: str) -> str:
    if len(value) < 2:
        return value
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
        value = value.replace('\\\\', '\\').replace('\\"', '"')
    return value


def cookie_parser(cookie_string: str) -> typing.Dict[str, str]:
    if len(cookie_string) > MAX_COOKIE_SIZE:
        raise RuntimeError("Cookie too large")
    cookie_dict: typing.Dict[str, str] = {}
    chunks=cookie_string.split(";")
    if len(chunks) > MAX_COOKIES:
        chunks = chunks[:MAX_COOKIES]
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, val = chunk.split("=", 1)
        else:
            key, val = "", chunk
        key = key.strip().translate(_HEADER_CLEAN_TRANS)
        val = val.strip().translate(_HEADER_CLEAN_TRANS)
        if key:
            cookie_dict[key] = _unquote_cookie_value(val)
    return cookie_dict


def query_parser(query_string: str):
    if len(query_string) > MAX_QUERY_SIZE:
        raise RuntimeError("Query too large")
    params = parse_qsl(query_string.decode("utf-8"), keep_blank_values=True)
    cleaned = {}
    for k, v in params:
        name = k.translate(_HEADER_CLEAN_TRANS)
        if not name:
            continue
        value = v.translate(_HEADER_CLEAN_TRANS)
        cleaned[name] = value
    return cleaned



class ClientDisconnect(Exception):
    pass