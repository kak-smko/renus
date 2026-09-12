from __future__ import annotations

from collections.abc import Iterable

from ._style import _Style

class Table:
    """Render rows (and optional headers) as an ASCII table."""

    __slots__ = ("_headers", "_sep_style")

    def __init__(
        self,
        headers: Iterable[object] | None = None,
        sep_style: _Style | None = None,
    ) -> None:
        """Initialize a Table.

        Parameters
        ----------
        headers:
            Optional column headers rendered on the first row.
        sep_style:
            Optional style applied to the separator line. Defaults to no style.
        """
        self._headers = headers
        self._sep_style = sep_style if sep_style is not None else _Style()

    def __call__(self, rows: Iterable[Iterable[object]]) -> str:
        return self._build(rows)

    def print(
        self,
        rows: Iterable[Iterable[object]],
        *,
        end: str = "\n",
        flush: bool = False,
    ) -> None:
        """Print the rendered table."""
        print(self._build(rows), end=end, flush=flush)

    def _build(self, rows: Iterable[Iterable[object]]) -> str:
        data = [[str(cell) for cell in row] for row in rows]
        if self._headers is not None:
            data.insert(0, [str(h) for h in self._headers])
        widths = [max(len(row[i]) for row in data) for i in range(len(data[0]))]
        seperator = self._sep_style("─" * (sum(widths) + len(widths) * 3 - 1))
        lines: list[str] = []
        for idx, row in enumerate(data):
            cells = " │ ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
            lines.append("│ " + cells + " │")
            if self._headers is not None and idx == 0:
                lines.append(seperator)
        top = "┌" + "─" * (len(lines[0]) - 2) + "┐" if lines else ""
        bottom = "└" + "─" * (len(lines[0]) - 2) + "┘" if lines else ""
        return "\n".join([top, *lines, bottom])
