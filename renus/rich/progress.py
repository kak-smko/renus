from __future__ import annotations

import sys

from ._style import _Style
from .style_context import lookup_style

__all__ = ["Progress"]

_FILLED = "█"
_EMPTY = "░"

def _resolve(name_or_style: object) -> _Style:
    if isinstance(name_or_style, _Style):
        return name_or_style
    style = lookup_style(str(name_or_style))
    return style if isinstance(style, _Style) else _Style()

class Progress:
    """Render and update an in-place terminal progress bar."""

    __slots__ = (
        "_total",
        "_current",
        "_width",
        "_label",
        "_bar_style",
        "_label_style",
    )

    def __init__(
        self,
        total: int,
        *,
        width: int = 40,
        label: str | None = None,
        bar_style: object = "green",
        label_style: object = "cyan",
    ) -> None:
        """Initialize a Progress bar.

        Parameters
        ----------
        total:
            Total units the bar runs to.
        width:
            Bar width in characters. Defaults to 40.
        label:
            Optional label rendered before the bar.
        bar_style:
            Name of a ``Terminal`` style (or style instance) for the bar.
            Defaults to ``"green"``.
        label_style:
            Name of a ``Terminal`` style (or style instance) for the label.
            Defaults to ``"cyan"``.
        """
        self._total = max(0, int(total))
        self._current = 0
        self._width = max(1, int(width))
        self._label = label
        self._bar_style = _resolve(bar_style)
        self._label_style = _resolve(label_style)

    def __call__(self) -> str:
        return self.render()

    def update(
        self,
        *,
        current: int | None = None,
        advance: int = 0,
        label: str | None = None,
    ) -> "Progress":
        """Move the bar to ``current`` (or forward by ``advance``) and update the label."""
        if current is not None:
            self._current = min(max(0, int(current)), self._total)
        else:
            self._current = min(self._current + max(0, int(advance)), self._total)
        if label is not None:
            self._label = label
        return self

    def advance(self, n: int = 1) -> "Progress":
        """Advance the bar by ``n`` units. Returns self."""
        return self.update(advance=n)

    def complete(self) -> "Progress":
        """Set the bar to its total. Returns self."""
        return self.update(current=self._total)

    def render(self) -> str:
        """Build the progress bar string for the current state."""
        ratio = self._current / self._total if self._total else float(self._current > 0)
        ratio = min(1.0, max(0.0, ratio))
        filled = int(round(ratio * self._width))
        bar = self._bar_style(_FILLED * filled) + _EMPTY * (self._width - filled)
        pct = f"{round(ratio * 100)}%"
        body = f"{bar} {pct} {self._current}/{self._total}"
        if self._label:
            body = f"{self._label_style(self._label)} {body}"
        return body

    def print(self, *, end: str | None = None, flush: bool = True) -> None:
        """Write the bar to stdout, overwriting the previous line."""
        if end is None:
            end = "\n" if self._current >= self._total else ""
        sys.stdout.write("\r" + self.render() + end)
        if flush:
            sys.stdout.flush()

    def print_inplace(self, *, flush: bool = True) -> None:
        """Print the bar without a trailing newline."""
        self.print(end="", flush=flush)

    def finish(self, *, complete: bool = False, flush: bool = True) -> "Progress":
        """Complete the bar (optionally) and print on a fresh line. Returns self."""
        if complete:
            self.complete()
        self.print(end="\n", flush=flush)
        return self

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.complete().print(flush=True)
        print()
