from __future__ import annotations

import os
import stat
from email.utils import formatdate
from hashlib import md5
from mimetypes import guess_type
from typing import Callable, Mapping, Optional
from urllib.parse import quote

import anyio

from renus.datastructures import Background
from renus.response.base import Response
from renus.response.exceptions import FileResponseError
from renus.response.gzip import GzipStreamer
from renus.response.status import Status

class FileResponse(Response):
    """Stream a file from disk as an HTTP response."""

    chunk_size = 4096

    def __init__(
        self,
        path: str,
        status_code: Status = Status.HTTP_200_OK,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[Background] = None,
        filename: Optional[str] = None,
        stat_result: Optional[os.stat_result] = None,
        method: Optional[str] = None,
        zipped: bool = True,
        on_end: Optional[Callable[[], None]] = None,
    ) -> None:
        """Initialize a file response.

        Parameters
        ----------
        path:
            Path to the file to stream.
        status_code:
            HTTP status code for the response.
        headers:
            Optional mapping of initial response headers.
        media_type:
            Response media type. Defaults to the guessed file MIME type.
        background:
            Optional task to run after the response is sent.
        filename:
            Optional download filename used in ``Content-Disposition``.
        stat_result:
            Optional pre-fetched file stat result.
        method:
            HTTP method; sets header-only responses for ``HEAD``.
        zipped:
            Compress the file with gzip when the client accepts it.
        on_end:
            Optional callback invoked after the file is sent.
        """
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
            self._set_content_disposition(self.filename)

        self.stat_result = stat_result
        if stat_result is not None:
            self.set_stat_headers(stat_result, False)

    def _set_content_disposition(self, filename: str) -> None:
        content_disposition_filename = quote(filename)
        if content_disposition_filename != filename:
            content_disposition = "attachment; filename*=utf-8''{}".format(
                content_disposition_filename
            )
        else:
            content_disposition = 'attachment; filename="{}"'.format(filename)
        self.raw_headers.append(
            (b"content-disposition", content_disposition.encode("utf-8"))
        )

    def set_stat_headers(self, stat_result: os.stat_result, is_zip: bool) -> None:
        """Add stat-derived headers (length, modified, etag)."""
        content_length = str(stat_result.st_size)
        last_modified = formatdate(stat_result.st_mtime, usegmt=True)
        etag_base = str(stat_result.st_mtime) + "-" + str(stat_result.st_size)
        etag = md5(etag_base.encode()).hexdigest()
        if not is_zip:
            self.raw_headers.append((b"content-length", content_length.lower().encode("utf-8")))
        self.raw_headers.append((b"last-modified", last_modified.lower().encode("utf-8")))
        self.raw_headers.append((b"etag", etag.lower().encode("utf-8")))

    async def __call__(self, request, scope, receive, send) -> None:
        """Stream the file over the ASGI interface."""
        headers = request.headers
        is_zip = (
            self.zipped
            and "gzip" in headers.get("accept-encoding", "")
            and not self.send_header_only
        )
        zipper = GzipStreamer() if is_zip else None
        self.raw_headers.append(
            (b"content-encoding", ("gzip" if is_zip else "none").encode("utf-8"))
        )

        if self.stat_result is None:
            try:
                stat_result = await anyio.to_thread.run_sync(os.stat, self.path)
            except FileNotFoundError:
                raise FileResponseError(f"File at path {self.path} does not exist.") \
                    from None
            if not stat.S_ISREG(stat_result.st_mode):
                raise FileResponseError(
                    f"File at path {self.path} is not a file."
                ) from None
            self.set_stat_headers(stat_result, is_zip)

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
                    if zipper is not None:
                        chunk = zipper.write(chunk)
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": more_body,
                        }
                    )
            if zipper is not None:
                trailer = zipper.finish()
                if trailer:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": trailer,
                            "more_body": False,
                        }
                    )
        if self.on_end is not None:
            self.on_end()
        if self.background is not None:
            await self.background()
