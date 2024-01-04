import asyncio
import tempfile
import typing

from renus.core.concurrency import run_in_threadpool


class Background:
    def __init__(
        self, func: typing.Callable, *args: typing.Any, **kwargs: typing.Any
    ) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.is_async = asyncio.iscoroutinefunction(func)

    async def __call__(self) -> None:
        if self.is_async:
            await self.func(*self.args, **self.kwargs)
        else:
            await run_in_threadpool(self.func, *self.args, **self.kwargs)

class MultiDict(typing.Mapping):
    def __init__(
        self,
        *args: typing.Union[
            "MultiDict",
            typing.Mapping,
            typing.List[typing.Tuple[typing.Any, typing.Any]],
        ],
        **kwargs: typing.Any,
    ) -> None:
        assert len(args) < 2, "Too many arguments."

        if args:
            value = args[0]
        else:
            value = []

        if kwargs:
            value = (
                MultiDict(value).multi_items()
                + MultiDict(kwargs).multi_items()
            )

        if not value:
            _items = []  # type: typing.List[typing.Tuple[typing.Any, typing.Any]]
        elif hasattr(value, "multi_items"):
            value = typing.cast(MultiDict, value)
            _items = list(value.multi_items())
        elif hasattr(value, "items"):
            value = typing.cast(typing.Mapping, value)
            _items = list(value.items())
        else:
            value = typing.cast(
                typing.List[typing.Tuple[typing.Any, typing.Any]], value
            )
            _items = list(value)

        self._dict = {k: v for k, v in _items}
        self._list = _items

    def keys(self) -> typing.KeysView:
        return self._dict.keys()

    def values(self) -> typing.ValuesView:
        return self._dict.values()

    def items(self) -> typing.ItemsView:
        return self._dict.items()

    def multi_items(self) -> typing.List[typing.Tuple[str, str]]:
        return list(self._list)

    def get(self, key: typing.Any, default: typing.Any = None) -> typing.Any:
        if key in self._dict:
            return self._dict[key]
        return default

    def __getitem__(self, key: typing.Any) -> str:
        return self._dict[key]

    def __contains__(self, key: typing.Any) -> bool:
        return key in self._dict

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._dict)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return sorted(self._list) == sorted(other._list)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        items = self.multi_items()
        return f"{class_name}({items!r})"


class UploadFile:

    spool_max_size = 1024 * 1024

    def __init__(
        self, filename: str, file: typing.IO = None, content_type: str = ""
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        if file is None:
            file = tempfile.SpooledTemporaryFile(max_size=self.spool_max_size)
        self.file = file

    @property
    def _in_memory(self) -> bool:
        rolled_to_disk = getattr(self.file, "_rolled", True)
        return not rolled_to_disk

    async def write(self, data: typing.Union[bytes, str]) -> None:
        if self._in_memory:
            self.file.write(data)  # type: ignore
        else:
            await run_in_threadpool(self.file.write, data)

    async def read(self, size: int = -1) -> typing.Union[bytes, str]:
        if self._in_memory:
            return self.file.read(size)
        return await run_in_threadpool(self.file.read, size)

    async def seek(self, offset: int) -> None:
        if self._in_memory:
            self.file.seek(offset)
        else:
            await run_in_threadpool(self.file.seek, offset)

    async def close(self) -> None:
        if self._in_memory:
            self.file.close()
        else:
            await run_in_threadpool(self.file.close)


class FormData(MultiDict):
    """
    An immutable multidict, containing both file uploads and text input.
    """

    def __init__(
            self,
            *args: typing.Union[
                "FormData",
                typing.Mapping[str, typing.Union[str, UploadFile]],
                typing.List[typing.Tuple[str, typing.Union[str, UploadFile]]],
            ],
            **kwargs: typing.Union[str, UploadFile],
    ) -> None:
        super().__init__(*args, **kwargs)

    async def close(self) -> None:
        for key, value in self.multi_items():
            if isinstance(value, UploadFile):
                await value.close()
