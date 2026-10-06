from __future__ import annotations

import typing
from urllib.parse import parse_qsl

from renus.datastructures import FormData, UploadFile
from renus.request.limits import MAX_BODY_SIZE, MAX_FORM_PARTS
from renus.request.options import parse_options_header

HeaderDict = typing.Mapping[str, typing.Any]
ChunkStream = typing.AsyncGenerator[bytes, None]
FormItem = typing.Union[str, UploadFile]

def _user_safe_decode(src: bytes, codec: str) -> str:
    try:
        return src.decode(codec)
    except (UnicodeDecodeError, LookupError):
        return src.decode("utf-8")

def _decode_ascii(value: bytes | None) -> str:
    return value.decode("latin-1") if value else ""

class FormParser:

    """Parse URL-encoded form request bodies."""

    def __init__(self, headers: HeaderDict, stream: ChunkStream) -> None:
        """Create a form parser.

        Parameters
        ----------
        headers:
            Incoming request headers.
        stream:
            Async stream yielding the request body chunks.
        """
        self.headers = headers
        self.stream = stream
        self.max_body_size = MAX_BODY_SIZE

    async def parse(self) -> FormData:
        """Parse the body stream into a form-data mapping."""
        body = await self._read_body()
        raw_items: list[tuple[str, str]] = parse_qsl(
            body.decode("utf-8", errors="replace"), keep_blank_values=True
        )
        items: typing.List[typing.Tuple[str, FormItem]] = list(raw_items)
        return FormData(items)

    async def _read_body(self) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in self.stream:
            total += len(chunk)
            if total > self.max_body_size:
                raise RuntimeError("Request body too large")
            chunks.append(chunk)
        return b"".join(chunks)

class MultiPartParser:

    """Parse multipart/form-data request bodies, including uploaded files."""

    _CRLF = b"\r\n"

    def __init__(self, headers: HeaderDict, stream: ChunkStream) -> None:
        """Create a multipart parser.

        Parameters
        ----------
        headers:
            Incoming request headers.
        stream:
            Async stream yielding the request body chunks.
        """
        self.headers = headers
        self.stream = stream
        self.max_body_size = MAX_BODY_SIZE
        self.max_parts = MAX_FORM_PARTS

    async def parse(self) -> FormData:
        """Parse the multipart body into a form-data mapping."""
        _, params = parse_options_header(self.headers["content-type"])
        charset = params.get("charset", "utf-8")
        boundary = params.get("boundary")
        if not boundary:
            raise ValueError("Missing multipart/form-data boundary parameter")

        body = await self._read_body()
        return await self._parse_parts(body, boundary.encode("latin-1"), charset)

    async def _read_body(self) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in self.stream:
            total += len(chunk)
            if total > self.max_body_size:
                raise RuntimeError("Request body too large")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _parse_parts(self, body: bytes, boundary: bytes, charset: str) -> FormData:
        delimiter = b"--" + boundary
        chunks = body.split(delimiter)
        items: list[tuple[str, FormItem]] = []
        part_count = 0
        for chunk in chunks[1:-1]:
            part_count += 1
            if part_count > self.max_parts:
                raise RuntimeError(
                    f"Multipart body exceeds the maximum of {self.max_parts} parts"
                )
            await self._parse_part(chunk, charset, items)
        return FormData(items)

    async def _parse_part(
        self,
        chunk: bytes,
        charset: str,
        items: list[tuple[str, FormItem]],
    ) -> None:
        if chunk.startswith(self._CRLF):
            chunk = chunk[2:]
        header_block, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            return
        if data.endswith(self._CRLF):
            data = data[:-2]

        headers = self._parse_headers(header_block)
        name, filename, file_content_type = self._parse_disposition(headers)

        if filename is not None:
            file = UploadFile(filename=filename, content_type=file_content_type)
            await file.write(data)
            await file.seek(0)
            items.append((name, file))
        else:
            items.append((name, _user_safe_decode(data, charset)))

    def _parse_headers(self, block: bytes) -> dict[str, bytes]:
        headers: dict[str, bytes] = {}
        for line in block.split(b"\r\n"):
            if not line or b":" not in line:
                continue
            field, _, value = line.partition(b":")
            headers[field.strip().decode("latin-1").lower()] = value.strip()
        return headers

    def _parse_disposition(
        self, headers: dict[str, bytes]
    ) -> tuple[str, str | None, str]:
        disposition = _decode_ascii(headers.get("content-disposition"))
        _, options = parse_options_header(disposition)
        name = options.get("name", "")
        filename = options.get("filename")
        content_type = _decode_ascii(headers.get("content-type"))
        return name, filename, content_type
