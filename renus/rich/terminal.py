from __future__ import annotations

from collections.abc import Iterable

from ._style import _Style
from .header import Header
from .markdown import Markdown
from .progress import Progress
from .table import Table

__all__ = ["Terminal"]

class Terminal:
    """Namespace of styles and helpers for rendering styled terminal output."""

    bold = _Style(1)
    dim = _Style(2)
    italic = _Style(3)
    underline = _Style(4)
    blink = _Style(5)
    inverse = _Style(7)
    hidden = _Style(8)
    strike = _Style(9)

    black = _Style(30)
    red = _Style(91)
    green = _Style(92)
    yellow = _Style(93)
    blue = _Style(94)
    magenta = _Style(95)
    pink = _Style(95)
    cyan = _Style(96)
    white = _Style(97)
    grey = _Style(37)

    bg_black = _Style(40)
    bg_red = _Style(41)
    bg_green = _Style(42)
    bg_yellow = _Style(43)
    bg_blue = _Style(44)
    bg_magenta = _Style(45)
    bg_pink = _Style(45)
    bg_cyan = _Style(46)
    bg_grey = _Style(47)
    bg_white = _Style(7)

    ok = _Style(92)
    info = _Style(96)
    warn = _Style(93)
    error = _Style(91)
    faint = _Style(2)

    @staticmethod
    def header(width: int = 60) -> Header:
        """Create a Header using the bold style.

        Parameters
        ----------
        width:
            Total width of the header line. Defaults to 60.
        """
        return Header(Terminal.bold, width)

    @staticmethod
    def table(
        headers: Iterable[object] | None = None,
        style_sep: str = "bold",
    ) -> Table:
        """Create a Table with the given headers and separator style.

        Parameters
        ----------
        headers:
            Optional column headers rendered on the first row.
        style_sep:
            Name of a ``Terminal`` style used for the separator. Defaults to
            ``"bold"``.
        """
        sep = getattr(Terminal, style_sep, None)
        return Table(headers, sep if isinstance(sep, _Style) else _Style())

    @staticmethod
    def markdown(text: str) -> str:
        """Render the given Markdown ``text`` to styled terminal output.

        Parameters
        ----------
        text:
            The Markdown source to render.
        """
        return Markdown.render(text)

    @staticmethod
    def progress(
        total: int,
        *,
        width: int = 40,
        label: str | None = None,
        bar_style: object = "green",
        label_style: object = "cyan",
    ) -> Progress:
        """Create a Progress bar for the given total.

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
        return Progress(
            total=total,
            width=width,
            label=label,
            bar_style=bar_style,
            label_style=label_style,
        )
