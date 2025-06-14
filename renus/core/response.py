import gzip
import http.cookies
import inspect
import io
import json
import os
import stat
import typing
from email.utils import formatdate
from functools import partial
from hashlib import md5
from mimetypes import guess_type
from urllib.parse import quote, quote_plus

import anyio

from renus.core.cache import Cache
from renus.core.concurrency import iterate_in_threadpool
from renus.core.crypt import FastEncryptor
from renus.core.datastructures import Background
from renus.core.serialize import jsonEncoder
from renus.core.status import Status
from renus.util.helper import get_random_string


class Response:
    media_type = "text/html"
    charset = "utf-8"

    def __init__(
            self,
            content: typing.Any = None,
            status_code: Status = Status.HTTP_200_OK,
            headers: dict = None,
            media_type: str = None,
            background: Background = None,
    ) -> None:
        self.status_code = status_code
        if media_type is not None:
            self.media_type = media_type
        self.body = self.render(content)
        self.init_headers(headers)
        self.background = background

    def render(self, content: typing.Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def init_headers(self, headers: typing.Mapping[str, str] = None) -> None:
        populate_content_type = True
        raw_headers = []
        if headers is not None:
            for k, v in headers.items():
                if k.lower() != 'content-length':
                    raw_headers.append((k.lower().encode("utf-8"), v.encode("utf-8")))

                if k.lower() == 'content-type':
                    populate_content_type = False

        content_type = self.media_type
        if content_type is not None and populate_content_type:
            if content_type.startswith("text/"):
                content_type += "; charset=" + self.charset
            raw_headers.append((b"content-type", content_type.encode("utf-8")))

        self.raw_headers = raw_headers

    def set_cookie(
            self,
            key: str,
            value: str = "",
            max_age: int = None,
            expires: int = None,
            path: str = "/",
            domain: str = None,
            secure: bool = False,
            httponly: bool = False,
            samesite: str = "lax",
    ) -> None:
        cookie = http.cookies.SimpleCookie()  # type: http.cookies.BaseCookie
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
            assert samesite.lower() in [
                "strict",
                "lax",
                "none",
            ], "samesite must be either 'strict', 'lax' or 'none'"
            cookie[key]["samesite"] = samesite
        cookie_val = cookie.output(header="").strip()
        self.raw_headers.append((b"set-cookie", cookie_val.encode("utf-8")))

    def delete_cookie(self, key: str, path: str = "/", domain: str = None) -> None:
        self.set_cookie(key, expires=0, max_age=0, path=path, domain=domain)

    async def __call__(self, request, scope, receive, send) -> None:
        headers = request.headers
        if "gzip" in headers.get("accept-encoding", "") and len(self.body) > 500:
            self.gzip_buffer = io.BytesIO()
            self.gzip_file = gzip.GzipFile(mode="wb", fileobj=self.gzip_buffer)
            self.gzip_file.write(self.body)
            self.gzip_file.close()
            self.body = self.gzip_buffer.getvalue()
            self.raw_headers.append((b"content-encoding", "gzip".encode("utf-8")))
        else:
            self.raw_headers.append((b"content-encoding", "none".encode("utf-8")))
        self.raw_headers.append((b"content-length", str(len(self.body)).encode("utf-8")))
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        await send({"type": "http.response.body", "body": self.body})

        if self.background is not None:
            await self.background()


class HtmlResponse(Response):
    media_type = "text/html"


class TextResponse(Response):
    media_type = "text/plain"

    def render(self, content: typing.Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return str(content).encode(self.charset)


class JsonResponse(Response):
    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        if isinstance(content, bytes):
            return content

        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=True,
            indent=None,
            separators=(",", ":"),
            cls=jsonEncoder
        ).encode("utf-8")


class JsonResponseRedirect(Response):

    def __init__(self, content: typing.Any = None, headers: dict = None,
                 background: Background = None) -> None:
        super().__init__(content, 307, headers, "application/json", background)

    def render(self, url: str) -> bytes:
        content = {"location": quote_plus(url, safe=":/%#?&=@[]!$&'()*+,;")}

        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            cls=jsonEncoder
        ).encode("utf-8")


class EncryptResponse(Response):
    media_type = "text/plain"

    def __init__(self, content: typing.Any, password: str, status_code: Status = Status.HTTP_200_OK,
                 headers: dict = None,
                 media_type: str = None, background: Background = None) -> None:
        self.password = password
        if headers is None:
            headers = {}

        headers["encrypted"] = '1'
        headers["encrypted_type"] = str(type(content))
        super().__init__(content, status_code, headers, media_type, background)

    def render(self, content: typing.Any) -> bytes:
        if isinstance(content, bytes):
            return content

        return FastEncryptor().encrypt(str(content), self.password).encode("utf-8")


class RedirectResponse(Response):
    def __init__(
            self,
            url: str,
            status_code: Status = Status.HTTP_307_TEMPORARY_REDIRECT,
            headers: dict = None,
            background: Background = None,
    ) -> None:
        if headers is None:
            headers = {}

        headers["location"] = quote_plus(url, safe=":/%#?&=@[]!$&'()*+,;")
        super().__init__(
            content=b"", status_code=status_code, headers=headers, background=background
        )


class StreamingResponse(Response):
    def __init__(
            self,
            content: typing.Any,
            status_code: Status = Status.HTTP_200_OK,
            headers: dict = None,
            media_type: str = None,
            background: Background = None,
            zipped: bool = True
    ) -> None:
        super().__init__()
        if inspect.isasyncgen(content):
            self.body_iterator = content
        else:
            self.body_iterator = iterate_in_threadpool(content)
        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = background
        self.zipped = zipped
        self.init_headers(headers)

    async def listen_for_disconnect(self, receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def stream_response(self, request, scope, send) -> None:
        headers = request.headers
        is_zip = False
        if self.zipped and "gzip" in headers.get("accept-encoding", ""):
            is_zip = True
            self.gzip_buffer = io.BytesIO()
            self.gzip_file = gzip.GzipFile(mode="wb", fileobj=self.gzip_buffer)
            self.raw_headers.append((b"content-encoding", "gzip".encode("utf-8")))
        else:
            self.raw_headers.append((b"content-encoding", "none".encode("utf-8")))

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            if is_zip:
                self.gzip_file.write(chunk)
                chunk = self.gzip_buffer.getvalue()
                self.gzip_buffer.seek(0)
                self.gzip_buffer.truncate()

            if not isinstance(chunk, bytes):
                chunk = chunk.encode(self.charset)

            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        chunk = b""
        if is_zip:
            self.gzip_file.write(chunk)
            self.gzip_file.close()
            chunk = self.gzip_buffer.getvalue()
            self.gzip_buffer.seek(0)
            self.gzip_buffer.truncate()
        await send({"type": "http.response.body", "body": chunk, "more_body": False})

    async def __call__(self, request, scope, receive, send) -> None:
        async with anyio.create_task_group() as task_group:
            async def wrap(func: "typing.Callable[[], typing.Awaitable[None]]") -> None:
                await func()
                task_group.cancel_scope.cancel()

            task_group.start_soon(wrap, partial(self.stream_response, request, scope, send))
            await wrap(partial(self.listen_for_disconnect, receive))
        if self.background is not None:
            await self.background()


class FileResponse(Response):
    chunk_size = 4096

    def __init__(
            self,
            path: str,
            status_code: Status = Status.HTTP_200_OK,
            headers: dict = None,
            media_type: str = None,
            background: Background = None,
            filename: str = None,
            stat_result: os.stat_result = None,
            method: str = None,
            zipped: bool = True,
            on_end=None
    ) -> None:
        super().__init__()
        self.path = path
        self.status_code = status_code
        self.background = background
        self.filename = filename
        self.on_end = on_end
        self.zipped = zipped
        self.send_header_only = method is not None and method.upper() == "HEAD"
        if media_type is None:
            media_type = guess_type(filename or path)[0] or "text/plain"
        self.media_type = media_type
        self.init_headers(headers)
        if self.filename is not None:
            content_disposition_filename = quote(self.filename)
            if content_disposition_filename != self.filename:
                content_disposition = "attachment; filename*=utf-8''{}".format(
                    content_disposition_filename
                )
            else:
                content_disposition = 'attachment; filename="{}"'.format(self.filename)
            self.raw_headers.append((b"content-disposition", content_disposition.lower().encode("utf-8")))

        self.stat_result = stat_result
        if stat_result is not None:
            self.set_stat_headers(stat_result, False)

    def set_stat_headers(self, stat_result: os.stat_result, is_zip) -> None:
        content_length = str(stat_result.st_size)
        last_modified = formatdate(stat_result.st_mtime, usegmt=True)
        etag_base = str(stat_result.st_mtime) + "-" + str(stat_result.st_size)
        etag = md5(etag_base.encode()).hexdigest()
        if not is_zip:
            self.raw_headers.append((b"content-length", content_length.lower().encode("utf-8")))
        self.raw_headers.append((b"last-modified", last_modified.lower().encode("utf-8")))
        self.raw_headers.append((b"etag", etag.lower().encode("utf-8")))

    async def __call__(self, request, scope, receive, send) -> None:
        headers = request.headers
        is_zip = False
        if self.zipped and "gzip" in headers.get("accept-encoding", "") and not self.send_header_only:
            is_zip = True
            self.gzip_buffer = io.BytesIO()
            self.gzip_file = gzip.GzipFile(mode="wb", fileobj=self.gzip_buffer)
            self.raw_headers.append((b"content-encoding", "gzip".encode("utf-8")))
        else:
            self.raw_headers.append((b"content-encoding", "none".encode("utf-8")))

        if self.stat_result is None:
            try:
                stat_result = await anyio.to_thread.run_sync(os.stat, self.path)
                self.set_stat_headers(stat_result, is_zip)
            except FileNotFoundError:
                raise RuntimeError(f"File at path {self.path} does not exist.")
            else:
                mode = stat_result.st_mode
                if not stat.S_ISREG(mode):
                    raise RuntimeError(f"File at path {self.path} is not a file.")

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        if self.send_header_only:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        else:
            async with await anyio.open_file(self.path, mode="rb") as file:
                more_body = True
                while more_body:
                    chunk = await file.read(self.chunk_size)
                    more_body = len(chunk) == self.chunk_size
                    if is_zip:
                        self.gzip_file.write(chunk)
                        if not more_body:
                            self.gzip_file.close()
                        chunk = self.gzip_buffer.getvalue()
                        self.gzip_buffer.seek(0)
                        self.gzip_buffer.truncate()

                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": more_body,
                        }
                    )
        if self.on_end is not None:
            self.on_end()
        if self.background is not None:
            await self.background()


class PrivateResponse(Response):
    media_type = "text/plain"

    def __init__(
            self,
            url: str,
            status_code: Status = Status.HTTP_200_OK,
            headers: dict = None,
            background: Background = None
    ) -> None:
        super().__init__(
            content=url, status_code=status_code, headers=headers, background=background
        )

    def render(self, content: typing.Any) -> bytes:
        if content is None:
            return b""
        rnd = get_random_string(50)
        Cache().put(rnd, 'access to private')
        content = f'/storage/private/{rnd}/{content}'
        return content.encode(self.charset)
