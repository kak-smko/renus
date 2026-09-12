from __future__ import annotations

import tempfile
from typing import BinaryIO, Optional, TextIO, Union

from renus.config import Config
from renus.util.concurrency import run_in_threadpool

from renus.datastructures.multidict import MultiDict

MAX_UPLOAD_SIZE: int = Config("app").get("max_upload_size", 50 * 1024 * 1024)

FileLike = Union[
    BinaryIO, TextIO, tempfile.SpooledTemporaryFile
]

class UploadFile:
    """Represents an uploaded file with async read/write access."""

    spool_max_size: int = 1024 * 1024

    __slots__ = ("filename", "content_type", "file")

    def __init__(
        self,
        filename: str,
        file: Optional[FileLike] = None,
        content_type: str = "",
    ) -> None:
        """Bind file metadata and an optional backing file.

        Parameters
        ----------
        filename:
            The name of the uploaded file.
        file:
            Optional backing file object; a spooled temp file is created if
            not provided.
        content_type:
            Optional MIME type of the uploaded file.
        """
        self.filename = filename
        self.content_type = content_type
        if file is None:
            file = tempfile.SpooledTemporaryFile(max_size=self.spool_max_size)
        self.file = file

    @property
    def _in_memory(self) -> bool:
        rolled = getattr(self.file, "_rolled", None)
        if rolled is None:
            return True
        return not rolled

    @property
    def size(self) -> int:
        """Return the current size of the file in bytes."""
        return self._size()

    def _size(self) -> int:
        file = self.file
        try:
            pos = file.tell()
        except (OSError, AttributeError):
            return 0
        try:
            file.seek(0, 2)
            end = file.tell()
            file.seek(pos)
            return max(end - pos, 0)
        except (OSError, AttributeError):
            return 0

    async def write(self, data: Union[bytes, str]) -> None:
        """Write the given data to the file."""
        if self._in_memory:
            self.file.write(data)
        else:
            await run_in_threadpool(self.file.write, data)

    async def read(self, size: int = -1):
        """Read up to ``size`` bytes from the file."""
        if self._in_memory:
            return self.file.read(size)
        return await run_in_threadpool(self.file.read, size)

    async def seek(self, offset: int) -> None:
        """Move the file position to the given offset."""
        if self._in_memory:
            self.file.seek(offset)
        else:
            await run_in_threadpool(self.file.seek, offset)

    async def close(self) -> None:
        """Close the backing file, releasing its resources."""
        if self._in_memory:
            self.file.close()
        else:
            await run_in_threadpool(self.file.close)

    async def __aenter__(self) -> "UploadFile":
        """Return self for use as an async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: object,
    ) -> None:
        """Close the file when leaving the async context manager."""
        await self.close()

    def __repr__(self) -> str:
        """Return a string representation of the uploaded file."""
        return (
            f"{type(self).__name__}(filename={self.filename!r}, "
            f"content_type={self.content_type!r}, size={self.size})"
        )

FormValue = Union[str, UploadFile]

class FormData(MultiDict[str, FormValue]):
    """MultiDict-shaped collection of form fields and uploaded files."""

    def __init__(
        self,
        values: Union[
            "FormData",
            "MultiDict[str, FormValue]",
            "dict[str, FormValue]",
            "list[tuple[str, FormValue]]",
        ],
        **kwargs: FormValue,
    ) -> None:
        """Populate the form data from values and keyword arguments.

        Parameters
        ----------
        values:
            Initial data: another FormData, a MultiDict, a mapping, or a list
            of ``(key, value)`` pairs.
        **kwargs:
            Additional fields merged into the form data.
        """
        super().__init__(values, **kwargs)

    async def close(self) -> None:
        """Close all uploaded files contained in the form data."""
        for _key, value in self.multi_items():
            if isinstance(value, UploadFile):
                await value.close()
