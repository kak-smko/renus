from __future__ import annotations

from typing import Any

class Header:
    """Render a header line with an optional total width."""

    __slots__ = ("_style", "_width")

    def __init__(self, style: Any, width: int = 60) -> None:
        """Initialize a Header.

        Parameters
        ----------
        style:
            Style used to render the header text.
        width:
            Total width of the header line. Defaults to 60.
        """
        self._style = style
        self._width = width

    def __call__(self, txt: object) -> str:
        return self._build(txt)

    def print(self, txt: object, *, end: str = "\n", flush: bool = False) -> None:
        """Print the rendered header line."""
        print(self._build(txt), end=end, flush=flush)

    def _build(self, txt: object) -> str:
        text = str(txt)
        pad = max(0, self._width - len(text) - 2)
        left, right = pad // 2, pad - pad // 2
        line = f"{'=' * left} {text} {'=' * right}"
        return self._style(line)
