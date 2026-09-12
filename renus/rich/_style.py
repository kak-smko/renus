from __future__ import annotations

import sys
from collections.abc import Callable

from renus.config import Config

_config = Config("app")

_RESET = "\033[0m"

def _resolved() -> bool:
    switch = _config.get("color")
    if switch is None:
        return sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
    return bool(switch)

color_enabled = _resolved()

class _Style:

    __slots__ = ("_codes",)

    def __init__(self, *codes: int) -> None:
        self._codes = tuple(codes)

    def __call__(self, txt: object) -> str:
        text = str(txt)
        if not color_enabled or not self._codes:
            return text
        codes = ";".join(str(c) for c in self._codes)
        return f"\033[{codes}m{text}{_RESET}"

    def _with(self, *more: "_Style") -> "_Style":
        merged: list[int] = list(self._codes)
        for style in more:
            for code in style._codes:
                if code not in merged:
                    merged.append(code)
        return _Style(*merged)

    def print(self, txt: object, *, end: str = "\n", flush: bool = False) -> None:
        print(self(txt), end=end, flush=flush)

    def write(self, txt: object, *, end: str = "") -> None:
        print(self(txt), end=end, flush=False)

    def header(self, width: int = 60) -> "Header":
        from .header import Header

        return Header(self, width)

    def __getattr__(self, name: str) -> Callable[[object], str]:

        from .terminal import Terminal

        parent = getattr(Terminal, name, None)
        if isinstance(parent, _Style):
            return self._with(parent)
        raise AttributeError(name)
