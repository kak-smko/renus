from __future__ import annotations

from collections.abc import Iterable
import re

from ._style import _Style

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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
        data = [
            [self._cell_lines(cell) for cell in row]
            for row in rows
        ]
        if self._headers is not None:
            data.insert(0, [self._cell_lines(header) for header in self._headers])
        if not data:
            return ""

        column_count = max(len(row) for row in data)
        if column_count == 0:
            return ""
        for row in data:
            row.extend([""] for _ in range(column_count - len(row)))

        widths = [
            max(self._visible_width(line) for row in data for line in row[column])
            for column in range(column_count)
        ]
        separator = self._sep_style(
            "├" + "─" * (sum(widths) + len(widths) * 3 - 1) + "┤"
        )
        lines: list[str] = []
        for row_index, row in enumerate(data):
            row_height = max(len(cell) for cell in row)
            for line_index in range(row_height):
                cells = " │ ".join(
                    self._pad(
                        cell[line_index] if line_index < len(cell) else "",
                        widths[column],
                    )
                    for column, cell in enumerate(row)
                )
                lines.append("│ " + cells + " │")
            if self._headers is not None and row_index == 0:
                lines.append(separator)

        border_width = sum(widths) + len(widths) * 3 - 1
        top = "┌" + "─" * border_width + "┐"
        bottom = "└" + "─" * border_width + "┘"
        return "\n".join([top, *lines, bottom])

    @staticmethod
    def _cell_lines(cell: object) -> list[str]:
        text = str(cell).replace("\r\n", "\n").replace("\r", "\n")
        lines: list[str] = []
        active_codes: list[str] = []
        current_line = ""
        position = 0

        for match in re.finditer(r"\x1b\[[0-?]*[ -/]*[@-~]|\n", text):
            current_line += text[position:match.start()]
            token = match.group()
            position = match.end()
            if token == "\n":
                lines.append(current_line + ("\x1b[0m" if active_codes else ""))
                current_line = (
                    "\x1b[" + ";".join(active_codes) + "m" if active_codes else ""
                )
                continue

            current_line += token
            if token.endswith("m"):
                codes = token[2:-1].split(";")
                for code in codes:
                    if code in ("", "0"):
                        active_codes.clear()
                    elif code not in active_codes:
                        active_codes.append(code)

        current_line += text[position:]
        lines.append(current_line)
        return lines

    @staticmethod
    def _visible_width(text: str) -> int:
        return len(_ANSI_ESCAPE.sub("", text))

    @classmethod
    def _pad(cls, text: str, width: int) -> str:
        return text + " " * max(0, width - cls._visible_width(text))
