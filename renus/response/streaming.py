from __future__ import annotations

import inspect
from functools import partial
from typing import Any, Callable, Mapping, Optional

import anyio

from renus.util.concurrency import iterate_in_threadpool
from renus.datastructures import Background
from renus.response.base import Response
from renus.response.gzip import GzipStreamer
from renus.response.status import Status

class StreamingResponse(Response):
    """Stream a body from an async or sync iterable."""

    def __init__(
        self,
        content: Any,
        status_code: Status = Status.HTTP_200_OK,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[Background] = None,
        zipped: bool = False,
    ) -> None:
        """Initialize a streaming response.

        Parameters
        ----------
        content:
            Async or sync iterable yielding response body chunks.
        status_code:
            HTTP status code for the response.
        headers:
            Optional mapping of initial response headers.
        media_type:
            Response media type.
        background:
            Optional task to run after the response is sent.
        zipped:
            Compress chunks with gzip when the client accepts it.
        """
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
        """Wait until the client disconnects."""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break

    async def stream_response(self, request, scope, send) -> None:
        """Send the streaming body over the ASGI interface."""
        headers = request.headers
        is_zip = self.zipped and "gzip" in headers.get("accept-encoding", "")
        zipper = GzipStreamer() if is_zip else None
        self.raw_headers.append(
            (b"content-encoding", ("gzip" if is_zip else "none").encode("utf-8"))
        )

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            if not isinstance(chunk, bytes):
                chunk = chunk.encode(self.charset)
            if zipper is not None:
                chunk = zipper.write(chunk)
            if chunk:
                await send(
                    {"type": "http.response.body", "body": chunk, "more_body": True}
                )
        if zipper is not None:
            trailer = zipper.finish()
            if trailer:
                await send(
                    {"type": "http.response.body", "body": trailer, "more_body": True}
                )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, request, scope, receive, send) -> None:
        """Stream the response and track client disconnects."""
        async with anyio.create_task_group() as task_group:
            async def wrap(func: Callable[[], Any]) -> None:
                await func()
                task_group.cancel_scope.cancel()

            task_group.start_soon(wrap, partial(self.stream_response, request, scope, send))
            await wrap(partial(self.listen_for_disconnect, receive))
        if self.background is not None:
            await self.background()
