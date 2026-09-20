from __future__ import annotations

import gzip
import io

GZIP_MIN_LENGTH = 500

class GzipStreamer:
    """Streaming gzip compressor for response bodies."""

    __slots__ = ("_buffer", "_gzip", "_offset")

    def __init__(self) -> None:
        """Initialize an empty gzip compressor."""
        self._buffer = io.BytesIO()
        self._gzip = gzip.GzipFile(mode="wb", fileobj=self._buffer)
        self._offset = 0

    def write(self, chunk: bytes) -> bytes:
        """Compress ``chunk`` and return data written since the last call."""
        self._gzip.write(chunk)
        self._gzip.flush()
        return self._delta()

    def finish(self) -> bytes:
        """Finish compression and return the remaining data."""
        self._gzip.close()
        return self._delta()

    def compressed(self) -> bytes:
        """Return the fully compressed contents."""
        self._buffer.seek(0)
        return self._buffer.getvalue()

    def _delta(self) -> bytes:
        buffer = self._buffer
        buffer.seek(0, io.SEEK_END)
        end = buffer.tell()
        buffer.seek(self._offset)
        data = buffer.read(end - self._offset)
        self._offset = end
        return data
