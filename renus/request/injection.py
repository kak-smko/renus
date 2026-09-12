from __future__ import annotations

import typing

from html import unescape

from renus.request.xss import Xss

Primitive = typing.Union[None, bool, int, float, str]
Sanitizable = typing.Union[typing.Dict[str, typing.Any], typing.List[typing.Any], Primitive]

class Injection:

    """Sanitize request data to guard against XSS attacks."""

    def escape(self, value: str) -> str:
        """Escape XSS-sensitive content in a string."""
        parser = Xss()
        parser.feed(unescape(value))
        parser.close()
        return parser.getEscaped().strip()

    def protect(self, data: Sanitizable) -> Sanitizable:
        """Recursively sanitize nested structured data."""
        return self.__value_handle(data)

    def __list_handle(self, data: typing.List[typing.Any]) -> typing.List[typing.Any]:
        return [self.__value_handle(item) for item in data]

    def __dict_handle(self, obj: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        return {
            self.escape(str(key)): self.__value_handle(value) for key, value in obj.items()
        }

    def __value_handle(self, value: Sanitizable) -> Sanitizable:
        if value is None or type(value) in (bool, int, float):
            return value
        if isinstance(value, dict):
            return self.__dict_handle(value)
        if isinstance(value, list):
            return self.__list_handle(value)
        return self.escape(str(value))

__all__ = ["Injection"]
